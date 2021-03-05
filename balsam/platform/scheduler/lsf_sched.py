import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .scheduler import SchedulerBackfillWindow, SchedulerJobLog, SchedulerJobStatus, SubprocessSchedulerInterface

PathLike = Union[Path, str]
logger = logging.getLogger(__name__)


# parse "00:00:00:00" to minutes
def parse_clock(t_str: str) -> int:
    parts = t_str.split(":")
    n = len(parts)
    D = H = M = S = 0
    if n == 4:
        D, H, M, S = map(int, parts)
    elif n == 3:
        H, M, S = map(int, parts)
    elif n == 2:
        M, S = map(int, parts)

    return D * 24 * 60 + H * 60 + M + round(S / 60)


#   "02/17 15:56:28"
def parse_datetime(t_str: str) -> datetime.datetime:
    return datetime.datetime.strptime(t_str, "%m/%d %H:%M:%S")


class LsfScheduler(SubprocessSchedulerInterface):
    status_exe = "jobstat"
    submit_exe = "bsub"
    delete_exe = "bkill"
    backfill_exe = "bslots"
    default_submit_kwargs: Dict[str, str] = {}
    submit_kwargs_flag_map: Dict[str, str] = {}

    _queue_name = "batch"

    # maps scheduler states to Balsam states
    _job_states = {
        "PEND": "queued",
        "RUN": "running",
        "BLOCKED": "failed",
    }

    @staticmethod
    def _job_state_map(scheduler_state: str) -> str:
        return LsfScheduler._job_states.get(scheduler_state, "unknown")

    # maps Balsam status fields to the scheduler fields
    # should be a comprehensive list of scheduler status fields
    _status_run_fields = {
        "scheduler_id": "JobID",
        "username": "Username",
        "queue": "Queue",
        "project": "Project",
        "num_nodes": "Nodes",
        "time_remaining_min": "Remain",
        "start_time": "StartTime",
        "jobname": "JobName",
    }

    # maps Balsam status fields to the scheduler fields
    # should be a comprehensive list of scheduler status fields
    _status_pend_fields = {
        "scheduler_id": "JobID",
        "username": "Username",
        "queue": "Queue",
        "project": "Project",
        "num_nodes": "Nodes",
        "wall_time_min": "WallTime",
        "queue_time": "QueueTime",
        "priority": "Priority",
        "jobname": "JobName",
    }

    _status_block_fields = {
        "scheduler_id": "JobID",
        "username": "Username",
        "queue": "Queue",
        "project": "Project",
        "num_nodes": "Nodes",
        "wall_time_min": "WallTime",
        "message": "BlockReason",
    }

    # when reading these fields from the scheduler apply
    # these maps to the string extracted from the output
    @staticmethod
    def _status_field_map(balsam_field: str) -> Optional[Callable[[str], Any]]:
        status_field_map = {
            "scheduler_id": lambda id: int(id),
            "state": lambda state: str(state),
            "username": lambda username: str(username),
            "queue": lambda queue: str(queue),
            "num_nodes": lambda n: 0 if n == "-" else int(n),
            "wall_time_min": parse_clock,
            "start_time": parse_datetime,
            "queue_time": parse_datetime,
            "time_remaining_min": parse_clock,
            "project": lambda project: str(project),
            "jobname": lambda jobname: str(jobname),
        }
        return status_field_map.get(balsam_field, None)

    @staticmethod
    def _render_submit_args(
        script_path: PathLike, project: str, queue: str, num_nodes: int, wall_time_min: int, **kwargs: Any
    ) -> List[str]:
        args = [
            LsfScheduler.submit_exe,
            "-o",
            os.path.basename(os.path.splitext(script_path)[0]) + ".output",
            "-e",
            os.path.basename(os.path.splitext(script_path)[0]) + ".error",
            "-P",
            project,
            "-q",
            queue,
            "-nnodes",
            str(int(num_nodes)),
            "-W",
            str(int(wall_time_min)),
        ]
        # adding additional flags as needed, e.g. `-C knl`
        for key, default_value in LsfScheduler.default_submit_kwargs.items():
            flag = LsfScheduler.submit_kwargs_flag_map[key]
            value = kwargs.setdefault(key, default_value)
            args += [flag, value]

        args.append(str(script_path))
        return args

    @staticmethod
    def _render_status_args(
        project: Optional[str] = None, user: Optional[str] = None, queue: Optional[str] = None
    ) -> List[str]:
        args = [LsfScheduler.status_exe]
        if user is not None:
            args += ["-u", user]
        if project is not None:
            pass  # not supported
        if queue is not None:
            pass  # not supported on LSF
        return args

    @staticmethod
    def _render_delete_args(job_id: Union[int, str]) -> List[str]:
        return [LsfScheduler.delete_exe, str(job_id)]

    @staticmethod
    def _render_backfill_args() -> List[str]:
        return [LsfScheduler.backfill_exe, '-R"select[CN]"']

    @staticmethod
    def _parse_submit_output(submit_output: str) -> int:
        try:
            start = len("Job <")
            end = submit_output.find(">", start)
            scheduler_id = int(submit_output[start:end])
        except ValueError:
            scheduler_id = int(submit_output.split()[-1])
        return scheduler_id

    @staticmethod
    def _parse_status_output(raw_output: str) -> Dict[int, SchedulerJobStatus]:
        # Example output:
        # ------------------------------- Running Jobs: 1 (batch: 4619/4625=99.87% + batch-hm: 46/54=85.19%) -------------------------------
        # JobID      User       Queue    Project    Nodes Remain     StartTime       JobName
        # 697013     parton     batch    CSC388     1     19:35      01/27 16:28:13  Not_Specified
        # -------------------------------------------------------- Eligible Jobs: 1 --------------------------------------------------------
        # JobID      User       Queue    Project    Nodes Walltime   QueueTime       Priority JobName
        # 696996     parton     batch    CSC388     1     20:00      01/27 16:12:21  504.00   Not_Specified
        # -------------------------------------------------------- Blocked Jobs: 0 ---------------------------------------------------------
        status_dict = {}
        job_lines = raw_output.strip().split("\n")
        state = None
        run = False
        pend = False
        block = False
        for line in job_lines:
            if line.startswith("----"):
                if "Running" in line:
                    state = "running"
                    run = True
                    pend = False
                    block = False
                elif "Eligible" in line:
                    state = "queued"
                    run = False
                    pend = True
                    block = False
                elif "Blocked" in line:
                    state = "submit_failed"
                    run = False
                    pend = False
                    block = True
                else:
                    raise NotImplementedError
            elif line.startswith("JobID"):
                continue
            else:
                fields = line.split()
                if run:
                    # rejoin datetime
                    new_fields = fields[0:6]
                    new_fields.append(" ".join(fields[6:8]))
                    new_fields += fields[8:]
                    fields = new_fields
                    status = {
                        "state": state,
                        "wall_time_min": 0,
                        "queue": "batch",
                    }
                    job_stat = LsfScheduler._parse_job_status(fields, LsfScheduler._status_run_fields, status)
                elif pend:
                    # rejoin datetime
                    new_fields = fields[0:6]
                    new_fields.append(" ".join(fields[6:8]))
                    new_fields += fields[8:]
                    fields = new_fields
                    status = {
                        "state": state,
                        "time_remaining_min": 0,
                        "queue": "batch",
                    }
                    job_stat = LsfScheduler._parse_job_status(fields, LsfScheduler._status_pend_fields, status)
                elif block:
                    # rejoin block reason column
                    new_fields = fields[0:6]
                    new_fields.append(" ".join(fields[6:]))
                    fields = new_fields
                    status = {
                        "state": state,
                        "time_remaining_min": 0,
                        "wall_time_min": 0,
                        "queue": "batch",
                    }
                    job_stat = LsfScheduler._parse_job_status(fields, LsfScheduler._status_block_fields, status)
                else:
                    raise NotImplementedError

                status_dict[job_stat.scheduler_id] = job_stat
        return status_dict

    @staticmethod
    def _parse_job_status(
        fields: List[str], status_fields: Dict[str, str], status: Dict[str, Any]
    ) -> SchedulerJobStatus:
        actual = len(fields)
        expected = len(status_fields)
        if actual != expected:
            raise ValueError(f"Line has {actual} columns: expected {expected}:\n{fields}")
        for name, value in zip(status_fields, fields):
            func = LsfScheduler._status_field_map(name)
            if callable(func):
                status[name] = func(value)
        return SchedulerJobStatus(**status)

    @staticmethod
    def _parse_backfill_output(stdout: str) -> Dict[str, List[SchedulerBackfillWindow]]:
        raw_lines = stdout.split("\n")
        windows: Dict[str, List[SchedulerBackfillWindow]] = {LsfScheduler._queue_name: []}
        node_lines = raw_lines[1:]
        for line in node_lines:
            if len(line.strip()) == 0:
                continue
            windows[LsfScheduler._queue_name].append(LsfScheduler._parse_bslots_line(line))
        return windows

    @staticmethod
    def _parse_bslots_line(line: str) -> SchedulerBackfillWindow:
        parts = line.split()
        nodes = int(parts[0])
        backfill_time = 0
        if len(re.findall("hours.*minutes.*seconds", line)) > 0:
            backfill_time += int(parts[1]) * 60
            backfill_time += int(parts[3])
        elif len(re.findall("minutes.*seconds", line)) > 0:
            backfill_time += int(parts[1])

        return SchedulerBackfillWindow(num_nodes=nodes, wall_time_min=backfill_time)

    @staticmethod
    def _parse_logs(scheduler_id: Union[int, str], job_script_path: Optional[PathLike]) -> SchedulerJobLog:
        # TODO: Return job start/stop time from log file or command
        return SchedulerJobLog()