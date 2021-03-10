from balsam.site import ApplicationDefinition


class EigenCorr(ApplicationDefinition):
    """
    Runs XPCS-Eigen on an (H5, IMM) file pair from a remote location.

    Jobs do not require any command template parameters; instead,
    users provide `h5_in`, `imm_in`, and `h5_out` transfer items.
    """

    corr_exe = "/projects/datascience/aps/software/xpcs-eigen/build/corr"
    command_template = f"{corr_exe} inp.h5 -imm inp.imm"
    environment_variables = {
        "HDF5_USE_FILE_LOCKING": "FALSE",
        "OMP_NUM_THREADS": "64",
    }
    parameters = {}
    transfers = {
        "h5_in": {
            "required": True,
            "direction": "in",
            "local_path": "inp.h5",
            "description": "Input HDF5 file",
            "recursive": False,
        },
        "imm_in": {
            "required": True,
            "direction": "in",
            "local_path": "inp.imm",
            "description": "Input IMM file",
            "recursive": False,
        },
        "h5_out": {
            "required": True,
            "direction": "out",
            "local_path": "inp.h5",  # output is input, modified in-place
            "description": "Output H5 file",
            "recursive": False,
        },
    }
