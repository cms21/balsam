import logging
import os
import queue
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterator, Optional, Type, Union

from balsam._api.app import ApplicationDefinition, AppType
from balsam.schemas import JobState, JobUpdate
from balsam.site import BulkStatusUpdater, FixedDepthJobSource
from balsam.util import Process, SigHandler

if TYPE_CHECKING:
    from balsam.client import RESTClient

logger = logging.getLogger(__name__)
PathLike = Union[str, Path]


@contextmanager
def job_context(workdir: Path, stdout_filename: str) -> Iterator[None]:
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_cwd = os.getcwd()
    try:
        os.chdir(workdir)
    except FileNotFoundError:
        workdir.mkdir(parents=True, exist_ok=True)
        os.chdir(workdir)

    try:
        with open(workdir.joinpath(stdout_filename), "a") as fp:
            sys.stdout = fp
            sys.stderr = fp
            yield
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def transition(app: ApplicationDefinition) -> None:
    assert app.job.state is not None
    transition_func = {
        JobState.staged_in: app.preprocess,
        JobState.run_done: app.postprocess,
        JobState.run_error: app.handle_error,
        JobState.run_timeout: app.handle_timeout,
    }[app.job.state]
    try:
        msg = f"Running {transition_func.__name__} for Job {app.job.id}"
        logger.debug(msg)
        sys.stdout.write(f"#BALSAM {msg}\n")
        transition_func()
    except Exception as exc:
        logger.exception(f"An exception occured in {transition_func}: marking Job {app.job.id} FAILED")
        app.job.state = JobState.failed
        app.job.state_data = {
            "message": f"An exception occured in {transition_func}",
            "exception": str(exc),
        }


def read_pyapp_result(app: ApplicationDefinition) -> None:
    if app._app_type != AppType.PY_FUNC:
        return
    if app.job.state not in (JobState.run_done, JobState.run_error):
        return
    if not Path("job.out").is_file():
        logger.warning(f"Missing job.out in {Path.cwd()}")
        return

    return_line = None
    except_line = None
    ret_marker = "BALSAM-RETURN-VALUE"
    exc_marker = "BALSAM-EXCEPTION"
    with open("job.out") as fp:
        for line in fp:
            if ret_marker in line:
                return_line = line
                break
            elif exc_marker in line:
                except_line = line
                break

    if app.job._update_model is None:
        app.job._update_model = JobUpdate()

    if return_line:
        return_line = return_line[return_line.find(ret_marker) :]
        payload = return_line.split(None, 1)[1]
        app.job._update_model.serialized_return_value = payload
        app.job._update_model.serialized_exception = ""
        logger.debug(f"Set serialized_return_value for Job in {app.job.workdir}")
    elif except_line:
        except_line = except_line[except_line.find(exc_marker) :]
        payload = except_line.split(None, 1)[1]
        app.job._update_model.serialized_exception = payload
        app.job._update_model.serialized_return_value = ""
        logger.debug(f"Set serialized_exception for Job in {app.job.workdir}")


def run_worker(
    job_source: "FixedDepthJobSource",
    status_updater: "BulkStatusUpdater",
    app_cache: Dict[int, Type[ApplicationDefinition]],
    data_path: PathLike,
) -> None:
    sig_handler = SigHandler()
    data_path = Path(data_path).resolve()

    while not sig_handler.is_set():
        try:
            job = job_source.get(timeout=1)
        except queue.Empty:
            continue
        else:
            app_cls = app_cache[job.app_id]
            app = app_cls(job)
            workdir = data_path.joinpath(app.job.workdir)
            with job_context(workdir, "balsam.log"):
                transition(app)
                read_pyapp_result(app)

            update_data = job._update_model.dict(exclude_unset=True) if job._update_model else {}
            update_data["id"] = job.id
            update_data["state"] = job.state
            update_data["state_timestamp"] = datetime.utcnow()
            update_data["state_data"] = job.state_data

            assert job.id is not None and job.state is not None
            status_updater.put(**update_data)
            logger.debug(f"Job {job.id} advanced to {job.state}")
    logger.info("Signal: ProcessingWorker exit")


class ProcessingService(object):
    def __init__(
        self,
        client: "RESTClient",
        site_id: int,
        prefetch_depth: int,
        apps_path: Path,
        data_path: Path,
        filter_tags: Optional[Dict[str, str]] = None,
        num_workers: int = 5,
    ) -> None:
        self.site_id = site_id
        ApplicationDefinition._set_client(client)
        app_cache = {app.__app_id__: app for app in ApplicationDefinition.load_by_site(self.site_id).values()}
        self.job_source = FixedDepthJobSource(
            client=client,
            site_id=site_id,
            prefetch_depth=prefetch_depth,
            filter_tags=filter_tags,
            states={"STAGED_IN", "RUN_DONE", "RUN_ERROR", "RUN_TIMEOUT"},
            app_ids={app_id for app_id in app_cache if app_id is not None},
        )
        self.status_updater = BulkStatusUpdater(client)

        self.workers = [
            Process(
                target=run_worker,
                args=(
                    self.job_source,
                    self.status_updater,
                    app_cache,
                    data_path,
                ),
            )
            for _ in range(num_workers)
        ]
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.status_updater.start()
            self.job_source.start()
            for worker in self.workers:
                worker.start()
            self._started = True

    def terminate(self) -> None:
        self.job_source.terminate()
        for worker in self.workers:
            worker.terminate()

    def join(self) -> None:
        for worker in self.workers:
            worker.join()
        # Wait til workers DONE before killing status_updater:
        self.status_updater.terminate()
        self.job_source.join()
        self.status_updater.join()
