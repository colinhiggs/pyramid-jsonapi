from .related_get import (
    get_results,
    stages,
)


# Do what reated_get does but serialise as identifiers.
def workflow(view, stages):
    return get_results(view, stages).serialise(identifiers=True)
