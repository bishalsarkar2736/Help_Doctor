from app.core.celery import celery_app


def test_acks_late_and_reject_on_worker_lost_are_paired():
    conf = celery_app.conf
    # acks_late without reject_on_worker_lost silently loses tasks when a worker
    # is hard-killed — they must be enabled together.
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True


def test_prefetch_is_one_for_fair_dispatch():
    assert celery_app.conf.worker_prefetch_multiplier == 1
