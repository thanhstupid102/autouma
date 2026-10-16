from core.settings import Settings


def test_remove_trained_chara_sends_id_array():
    calls = []

    class FakeClient:
        def call(self, ep, args=None):
            calls.append((ep, args))

    from uma_api.client import UmaClient
    FakeClient.remove_trained_chara = UmaClient.remove_trained_chara
    FakeClient.set_trained_chara_lock = UmaClient.set_trained_chara_lock

    FakeClient().remove_trained_chara([5345, "5337", None])
    assert calls == [
        ("trained_chara/load", {}),
        ("trained_chara/remove", {"trained_chara_id_array": [5345, 5337]}),
    ]


def test_remove_trained_chara_unlocks_locked_before_remove():
    calls = []

    class FakeClient:
        def call(self, ep, args=None):
            calls.append((ep, args))

    from uma_api.client import UmaClient
    FakeClient.remove_trained_chara = UmaClient.remove_trained_chara
    FakeClient.set_trained_chara_lock = UmaClient.set_trained_chara_lock

    FakeClient().remove_trained_chara([5345, 5337], unlock_ids=[5337])
    assert calls == [
        ("trained_chara/load", {}),
        ("trained_chara/change_lock_multi", {"trained_chara_id_array": [5337], "lock_flag": 0, "icon_type": 0}),
        ("trained_chara/remove", {"trained_chara_id_array": [5345, 5337]}),
    ]


def test_remove_trained_chara_noop_on_empty():
    from uma_api.client import UmaClient

    class FakeClient:
        def call(self, ep, args=None):
            raise AssertionError("should not call")

    FakeClient.remove_trained_chara = UmaClient.remove_trained_chara
    assert FakeClient().remove_trained_chara([]) is None


def test_delete_parents_route_deletes_only_owned_and_cleans_cache(monkeypatch):
    # The account-scoped parents domain lives in backend/app/routers/parents/;
    # DeleteParentsRequest and the delete handler are behind ParentService.
    from backend.app.routers.parents.schemas.parent import DeleteParentsRequest
    from backend.app.routers.parents.services.parent_service import ParentService
    from uma_api.session import Session

    session = Session(name="delete-owned", base_dir=str(Settings.BASE_DIR))
    monkeypatch.setattr(session.runner, "snapshot", lambda: {"running": False})
    calls = []

    class FakeClient:
        def remove_trained_chara(self, ids, unlock_ids=None):
            calls.append((list(ids), list(unlock_ids or [])))

    session.client = FakeClient()
    session.dashboard_data = {
        "parents": [
            {"instance_id": 5345, "name": "Owned A"},
            {"instance_id": 5337, "name": "Owned B"},
        ]
    }
    session.parent_cards = {5345: [1], 5337: [2]}
    session.parent_rank_points = {5345: {"rank": 1}, 5337: {"rank": 2}}

    req = DeleteParentsRequest(instance_ids=[5345, 9999])
    res = ParentService(session).delete(req.instance_ids, req.unlock_locked)

    assert calls == [([5345], [])]
    assert res == {
        "success": True,
        "deleted": [5345],
        "parents": [{"instance_id": 5337, "name": "Owned B"}],
    }
    assert session.parent_cards == {5337: [2]}
    assert session.parent_rank_points == {5337: {"rank": 2}}


def test_delete_parents_route_blocks_unknown_ids(monkeypatch):
    # The account-scoped parents domain lives in backend/app/routers/parents/;
    # DeleteParentsRequest and the delete handler are behind ParentService.
    from backend.app.routers.parents.schemas.parent import DeleteParentsRequest
    from backend.app.routers.parents.services.parent_service import ParentService
    from uma_api.session import Session

    session = Session(name="delete-unknown", base_dir=str(Settings.BASE_DIR))
    monkeypatch.setattr(session.runner, "snapshot", lambda: {"running": False})

    class FakeClient:
        def remove_trained_chara(self, ids, unlock_ids=None):
            raise AssertionError("should not delete unknown ids")

    session.client = FakeClient()
    session.dashboard_data = {"parents": [{"instance_id": 5345, "name": "Owned A"}]}

    req = DeleteParentsRequest(instance_ids=[9999])
    res = ParentService(session).delete(req.instance_ids, req.unlock_locked)

    assert res == {"success": False, "detail": "No matching owned veterans to delete"}


def test_delete_parents_route_locked_requires_unlock_consent(monkeypatch):
    # The account-scoped parents domain lives in backend/app/routers/parents/;
    # DeleteParentsRequest and the delete handler are behind ParentService.
    from backend.app.routers.parents.schemas.parent import DeleteParentsRequest
    from backend.app.routers.parents.services.parent_service import ParentService
    from uma_api.session import Session

    session = Session(name="delete-locked", base_dir=str(Settings.BASE_DIR))
    monkeypatch.setattr(session.runner, "snapshot", lambda: {"running": False})
    calls = []

    class FakeClient:
        def remove_trained_chara(self, ids, unlock_ids=None):
            calls.append((list(ids), list(unlock_ids or [])))

    session.client = FakeClient()
    session.dashboard_data = {
        "parents": [{"instance_id": 5345, "name": "Locked A", "is_locked": 1}]
    }
    session.parent_cards = {5345: [1]}
    session.parent_rank_points = {5345: {"rank": 1}}

    # Without consent -> reports the locked ids, deletes nothing.
    req = DeleteParentsRequest(instance_ids=[5345])
    res = ParentService(session).delete(req.instance_ids, req.unlock_locked)
    assert res == {"success": False, "detail": "locked", "locked": [5345]}
    assert calls == []

    # With consent -> unlocks then removes.
    req = DeleteParentsRequest(instance_ids=[5345], unlock_locked=True)
    res = ParentService(session).delete(req.instance_ids, req.unlock_locked)
    assert calls == [([5345], [5345])]
    assert res["success"] is True
    assert res["deleted"] == [5345]
