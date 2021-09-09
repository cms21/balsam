import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

from balsam import schemas

from .app import ApplicationDefinition
from .manager import Manager
from .model import CreatableBalsamModel, Field, NonCreatableBalsamModel

if TYPE_CHECKING:
    from balsam._api.models import (  # noqa: F401
        App,
        BatchJob,
        EventLog,
        Job,
        JobManager,
        JobQuery,
        Session,
        Site,
        TransferItem,
    )
    from balsam.client import RESTClient

JobState = schemas.JobState
JobTransferItem = schemas.JobTransferItem
RUNNABLE_STATES = schemas.RUNNABLE_STATES
logger = logging.getLogger(__name__)


class SiteBase(CreatableBalsamModel):
    _create_model_cls = schemas.SiteCreate
    _update_model_cls = schemas.SiteUpdate
    _read_model_cls = schemas.SiteOut


class SiteManagerBase(Manager["Site"]):
    _api_path = "sites/"


class AppBase(CreatableBalsamModel):
    _create_model_cls = schemas.AppCreate
    _update_model_cls = schemas.AppUpdate
    _read_model_cls = schemas.AppOut


class AppManagerBase(Manager["App"]):
    _api_path = "apps/"


class BatchJobBase(CreatableBalsamModel):
    _create_model_cls = schemas.BatchJobCreate
    _update_model_cls = schemas.BatchJobUpdate
    _read_model_cls = schemas.BatchJobOut
    # These fields overwritten by the generated subclass anyway
    # Used for type checking the methods below
    queue: Field[str]
    project: Field[str]
    num_nodes: Field[int]
    wall_time_min: Field[int]
    partitions: Field[Optional[List[schemas.BatchJobPartition]]]
    optional_params: Field[Dict[str, str]]

    def validate(
        self,
        allowed_queues: Dict[str, schemas.AllowedQueue],
        allowed_projects: List[str],
        optional_batch_job_params: Dict[str, str],
    ) -> None:
        if self.queue not in allowed_queues:
            raise ValueError(f"Unknown queue {self.queue} " f"(known: {list(allowed_queues.keys())})")
        queue = allowed_queues[self.queue]
        if self.num_nodes > queue.max_nodes:
            raise ValueError(f"{self.num_nodes} exceeds queue max num_nodes {queue.max_nodes}")
        if self.num_nodes < 1:
            raise ValueError("self size must be at least 1 node")
        if self.wall_time_min > queue.max_walltime:
            raise ValueError(f"{self.wall_time_min} exceeds queue max wall_time_min {queue.max_walltime}")

        if self.project not in allowed_projects:
            raise ValueError(f"Unknown project {self.project} " f"(known: {allowed_projects})")
        if self.partitions:
            if sum(part.num_nodes for part in self.partitions) != self.num_nodes:
                raise ValueError("Sum of partition sizes must equal batchjob num_nodes")

        extras = set(self.optional_params.keys())
        allowed_extras = set(optional_batch_job_params.keys())
        extraneous = extras.difference(allowed_extras)
        if extraneous:
            raise ValueError(f"Extraneous optional_params: {extraneous} " f"(allowed extras: {allowed_extras})")

    def partitions_to_cli_args(self) -> str:
        if not self.partitions:
            return ""
        args = ""
        for part in self.partitions:
            job_mode = part.job_mode
            num_nodes = part.num_nodes
            filter_tags = ":".join(f"{k}={v}" for k, v in part.filter_tags.items())
            args += f" --part {job_mode}:{num_nodes}"
            if filter_tags:
                args += f":{filter_tags}"
        return args


class BatchJobManagerBase(Manager["BatchJob"]):
    _api_path = "batch-jobs/"
    _bulk_update_enabled = True


InputAppType = Union[int, str, ApplicationDefinition]


class JobBase(CreatableBalsamModel):
    _create_model_cls = schemas.JobCreate
    _update_model_cls = schemas.JobUpdate
    _read_model_cls = schemas.JobOut

    _app_name_cache: Dict[Tuple[Optional[str], str], ApplicationDefinition] = {}
    _app_id_cache: Dict[int, ApplicationDefinition] = {}
    objects: "JobManager"
    app_id: Field[int]
    workdir: Field[Path]
    parent_ids: Field[Set[int]]

    def __init__(self, app: InputAppType, site_name: Optional[str] = None, **kwargs: Any) -> None:
        app_id = self._resolve_app_id(app, site_name)
        super().__init__(**kwargs, app_id=app_id)

    @classmethod
    def _fetch_app_by_name(cls, app_name: str, site_name: Optional[str]) -> ApplicationDefinition:
        app_key = (site_name, app_name)
        if app_key not in cls._app_name_cache:
            AppManager = cls.objects._client.App.objects
            logger.debug(f"App Cache miss: fetching app {app_key}")
            app = AppManager.get(site_name=site_name, name=app_name)
            assert app.id is not None
            cls._app_name_cache[app_key] = app
            cls._app_id_cache[app.id] = app
        return cls._app_name_cache[app_key]

    @classmethod
    def _fetch_app_by_id(cls, app_id: int) -> ApplicationDefinition:
        if app_id not in cls._app_id_cache:
            AppManager = cls.objects._client.App.objects
            logger.debug(f"App Cache miss: fetching app {app_id}")
            app = AppManager.get(id=app_id)
            cls._app_id_cache[app_id] = app
        return cls._app_id_cache[app_id]

    @classmethod
    def _resolve_app_id(cls, app: Union[str, int, ApplicationDefinition], site_name: Optional[str]) -> int:
        if isinstance(app, int):
            app_id = app
        elif isinstance(app, str):
            app = cls._fetch_app_by_name(app, site_name)
            assert app.id is not None
            app_id = app.id
        else:
            if app.__app_id__ is None:
                raise ValueError(
                    f"Cannot resolve ID from ApplicationDefinition {app}: __app_id__ is None. You need to app.sync() prior to creating Jobs with this app."
                )
            app_id = app.__app_id__
            cls._app_id_cache[app_id] = app
        return app_id

    @property
    def app(self) -> ApplicationDefinition:
        if self.app_id is None:
            raise ValueError("Cannot fetch by app ID; is None")
        return self._fetch_app_by_id(self.app_id)

    @property
    def site_id(self) -> int:
        if self.app_id is None:
            raise ValueError("Cannot fetch by app ID; is None")
        return self._fetch_app_by_id(self.app_id).site_id

    def resolve_workdir(self, data_path: Path) -> Path:
        return data_path.joinpath(self.workdir)

    def parent_query(self) -> "JobQuery":
        return self.objects.filter(id=list(self.parent_ids))


class JobManagerBase(Manager["Job"]):
    _api_path = "jobs/"
    _bulk_create_enabled = True
    _bulk_update_enabled = True
    _bulk_delete_enabled = True


class SessionBase(CreatableBalsamModel):
    _create_model_cls = schemas.SessionCreate
    _update_model_cls = None
    _read_model_cls = schemas.SessionOut
    objects: "SessionManagerBase"

    def acquire_jobs(
        self,
        max_num_jobs: int,
        max_wall_time_min: Optional[int] = None,
        max_nodes_per_job: Optional[int] = None,
        max_aggregate_nodes: Optional[float] = None,
        serial_only: bool = False,
        filter_tags: Optional[Dict[str, str]] = None,
        states: Set[JobState] = RUNNABLE_STATES,
        app_ids: Optional[Set[int]] = None,
    ) -> "List[Job]":
        if filter_tags is None:
            filter_tags = {}
        if app_ids is None:
            app_ids = set()
        return self.__class__.objects._do_acquire(
            self,
            max_num_jobs=max_num_jobs,
            max_wall_time_min=max_wall_time_min,
            max_nodes_per_job=max_nodes_per_job,
            max_aggregate_nodes=max_aggregate_nodes,
            serial_only=serial_only,
            filter_tags=filter_tags,
            states=states,
            app_ids=app_ids,
        )

    def tick(self) -> None:
        return self.__class__.objects._do_tick(self)


class SessionManagerBase(Manager["Session"]):
    _api_path = "sessions/"
    _client: "RESTClient"

    def _do_acquire(self, instance: "SessionBase", **kwargs: Any) -> "List[Job]":
        from balsam._api.models import Job, JobManager

        Job.objects = JobManager(client=self._client)

        acquired_raw = self._client.post(self._api_path + f"{instance.id}", **kwargs)
        jobs = [Job._from_api(dat) for dat in acquired_raw]
        return jobs

    def _do_tick(self, instance: "SessionBase") -> None:
        self._client.put(self._api_path + f"{instance.id}")


class TransferItemBase(NonCreatableBalsamModel):
    _create_model_cls = None
    _update_model_cls = schemas.TransferItemUpdate
    _read_model_cls = schemas.TransferItemOut


class TransferItemManagerBase(Manager["TransferItem"]):
    _api_path = "transfers/"
    _bulk_update_enabled = True


class EventLogBase(NonCreatableBalsamModel):
    _create_model_cls = None
    _update_model_cls = None
    _read_model_cls = schemas.LogEventOut


class EventLogManagerBase(Manager["EventLog"]):
    _api_path = "events/"
