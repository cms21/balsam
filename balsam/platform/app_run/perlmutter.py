import time

from .app_run import SubprocessAppRun


class PerlmutterGPURun(SubprocessAppRun):
    """
    https://slurm.schedmd.com/srun.html
    """

    def _build_cmdline(self) -> str:
        node_ids = [h for h in self._node_spec.hostnames]
        num_nodes = str(len(node_ids))
        num_ranks = self.get_num_ranks()
        if num_ranks == 1:
            network_args = ["--gres=craynetwork:0"]
        else:
            network_args = []

        if self._gpus_per_rank > 0:
            gpu_args = ["--gpus-per-task", self._gpus_per_rank]
        else:
            gpu_args = []

        args = [
            "srun",
            *network_args,
            "-n",
            self.get_num_ranks(),
            "--ntasks-per-node",
            self._ranks_per_node,
            *gpu_args,
            "--nodelist",
            ",".join(node_ids),
            "--nodes",
            num_nodes,
            "--cpus-per-task",
            self.get_cpus_per_rank(),
            "--mem=40G",
            "--overlap",
            self._cmdline,
        ]
        return " ".join(str(arg) for arg in args)

    def _pre_popen(self) -> None:
        time.sleep(0.01)
