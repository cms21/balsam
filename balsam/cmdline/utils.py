import click

from balsam.config import SiteConfig


def list_to_dict(arg_list):
    return dict(arg.split("=") for arg in arg_list)


def validate_tags(ctx, param, value):
    try:
        return list_to_dict(value)
    except ValueError:
        raise click.BadParameter("needs to be in format KEY=VALUE")


def validate_partitions(ctx, param, value):
    partitions = []
    for arg in value:
        try:
            job_mode, num_nodes, *filter_tags = value.split(":")
        except ValueError:
            raise click.BadParameter("needs to be in format MODE:NUM_NODES[:KEY=VALUE]")
        filter_tags = validate_tags(ctx, param, filter_tags)
        partitions.append({"job_mode": job_mode, "num_nodes": num_nodes, "filter_tags": filter_tags})
    return partitions


def load_site_config() -> SiteConfig:
    try:
        cf = SiteConfig()
    except ValueError:
        raise click.BadParameter(
            "Cannot perform this action outside the scope of a Balsam Site. "
            "Please navigate into a Balsam site directory, or set "
            "BALSAM_SITE_PATH"
        )
    return cf
