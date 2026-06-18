import pytest
import os
import tempfile
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from models import Base, init_db, Clue, User, FollowupRecord, AssignmentRule
from main import app, get_db, get_session_factory


def _make_test_app(db_url: str = "sqlite://"):
    if db_url == "sqlite://":
        engine = create_engine(
            db_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db(engine, TestSession)

    app.state.engine = engine
    app.state.session_factory = TestSession

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = lambda: TestSession
    return app, engine, TestSession


@pytest.fixture
def client():
    test_app, engine, session_factory = _make_test_app("sqlite://")
    with TestClient(test_app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def file_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for f in [path, path + "-shm", path + "-wal"]:
        if os.path.exists(f):
            os.unlink(f)


class TestAutoAssignment:
    def test_clue_auto_assigned_on_create(self, client):
        r = client.post("/api/clues", json={
            "title": "华北官网高优线索",
            "customer_name": "测试客户A",
            "phone": "13800001111",
            "source": "官网",
            "region": "华北",
            "priority": "high",
            "description": "测试自动分派"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["assignee_id"] is not None, "线索创建后应自动分派负责人"
        assert data["assignee_name"] is not None
        assert data["stage"] == "new"

    def test_assignment_matches_rules(self, client):
        r = client.post("/api/clues", json={
            "title": "华北官网高优",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "A", "phone": ""
        })
        assert r.status_code == 200
        assert r.json()["assignee_name"] == "张三"

        r = client.post("/api/clues", json={
            "title": "华东官网高优",
            "source": "官网", "region": "华东", "priority": "high",
            "customer_name": "B", "phone": ""
        })
        assert r.status_code == 200
        assert r.json()["assignee_name"] == "李四"

        r = client.post("/api/clues", json={
            "title": "转介绍高优",
            "source": "转介绍", "region": "华南", "priority": "high",
            "customer_name": "C", "phone": ""
        })
        assert r.status_code == 200
        assert r.json()["assignee_name"] == "王五"

        r = client.post("/api/clues", json={
            "title": "低优先级",
            "source": "其他", "region": "西南", "priority": "low",
            "customer_name": "D", "phone": ""
        })
        assert r.status_code == 200
        assert r.json()["assignee_name"] == "赵六"

    def test_kanban_reflects_auto_assignment(self, client):
        client.post("/api/clues", json={
            "title": "看板验证线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "E", "phone": ""
        })
        r = client.get("/api/kanban")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert data["today_new"] >= 1
        new_clues = data["by_stage"]["new"]
        assert any(c["assignee_name"] is not None for c in new_clues)


class TestDuplicateReassignment:
    def test_reassign_to_same_person_rejected(self, client):
        r = client.post("/api/clues", json={
            "title": "转派测试线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "F", "phone": ""
        })
        clue = r.json()
        assignee_id = clue["assignee_id"]

        r2 = client.post(f"/api/clues/{clue['id']}/reassign", json={"target_user_id": assignee_id})
        assert r2.status_code == 400
        detail = r2.json()["detail"]
        assert "已由" in detail or "负责" in detail, f"错误提示应包含当前负责人信息，实际: {detail}"

    def test_reassign_to_different_person_succeeds(self, client):
        r = client.post("/api/clues", json={
            "title": "正常转派测试",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "G", "phone": ""
        })
        clue = r.json()
        original_assignee = clue["assignee_id"]

        other_user_id = 2 if original_assignee != 2 else 3
        r2 = client.post(f"/api/clues/{clue['id']}/reassign", json={"target_user_id": other_user_id})
        assert r2.status_code == 200
        assert r2.json()["assignee_id"] == other_user_id

    def test_reassign_to_same_person_shows_current_owner_name(self, client):
        r = client.post("/api/clues", json={
            "title": "提示负责人测试",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "H", "phone": ""
        })
        clue = r.json()
        r2 = client.post(f"/api/clues/{clue['id']}/reassign", json={"target_user_id": clue["assignee_id"]})
        detail = r2.json()["detail"]
        assert clue["assignee_name"] in detail, f"提示信息应包含负责人姓名，实际: {detail}"


class TestFollowupUpdates:
    def test_followup_updates_stage(self, client):
        r = client.post("/api/clues", json={
            "title": "跟进阶段测试",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "I", "phone": ""
        })
        clue = r.json()
        assert clue["stage"] == "new"

        next_time = (datetime.utcnow() + timedelta(days=2)).isoformat()
        r2 = client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "首次电话联系，客户表示有兴趣",
            "stage_after": "contacted",
            "next_followup_at": next_time,
            "created_by": "测试"
        })
        assert r2.status_code == 200
        assert r2.json()["stage_after"] == "contacted"

        r3 = client.get(f"/api/clues/{clue['id']}")
        updated = r3.json()
        assert updated["stage"] == "contacted", "跟进后阶段应更新"

    def test_followup_updates_last_followup_time(self, client):
        r = client.post("/api/clues", json={
            "title": "跟进时间测试",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "J", "phone": ""
        })
        clue = r.json()
        assert clue["last_followup_at"] is None

        before = datetime.utcnow()
        r2 = client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "添加跟进记录",
            "stage_after": "contacted",
            "created_by": "测试"
        })
        after = datetime.utcnow()
        assert r2.status_code == 200

        r3 = client.get(f"/api/clues/{clue['id']}")
        updated = r3.json()
        assert updated["last_followup_at"] is not None, "跟进后最后跟进时间应更新"
        followup_time = datetime.fromisoformat(updated["last_followup_at"])
        assert before <= followup_time <= after

    def test_kanban_stage_reflects_followup(self, client):
        r = client.post("/api/clues", json={
            "title": "看板阶段更新测试",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "K", "phone": ""
        })
        clue = r.json()

        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "推进到已联系",
            "stage_after": "contacted",
            "created_by": "测试"
        })

        r2 = client.get("/api/kanban")
        data = r2.json()
        contacted_clues = data["by_stage"]["contacted"]
        assert any(c["id"] == clue["id"] for c in contacted_clues), "看板应反映跟进后的阶段变化"

    def test_kanban_today_followup_increments(self, client):
        r = client.post("/api/clues", json={
            "title": "今日跟进计数",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "L", "phone": ""
        })
        clue = r.json()

        r_before = client.get("/api/kanban")
        before_count = r_before.json()["today_followup"]

        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "今日跟进",
            "stage_after": "contacted",
            "created_by": "测试"
        })

        r_after = client.get("/api/kanban")
        after_count = r_after.json()["today_followup"]
        assert after_count > before_count, "今日跟进数应在跟进后增加"


class TestOverdueReminder:
    def test_overdue_generated_for_past_followup(self, client):
        r = client.post("/api/clues", json={
            "title": "逾期测试线索",
            "source": "其他", "region": "华中", "priority": "low",
            "customer_name": "逾期客户", "phone": ""
        })
        clue = r.json()

        past_time = (datetime.utcnow() - timedelta(days=3)).isoformat()
        r2 = client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设置过去的下次跟进时间",
            "stage_after": "contacted",
            "next_followup_at": past_time,
            "created_by": "测试"
        })
        assert r2.status_code == 200

        r3 = client.post("/api/clues/check-overdue")
        assert r3.status_code == 200
        result = r3.json()
        assert result["total_overdue"] >= 1, "应有逾期线索"

    def test_overdue_list_contains_clue(self, client):
        r = client.post("/api/clues", json={
            "title": "逾期列表测试",
            "source": "其他", "region": "华中", "priority": "low",
            "customer_name": "逾期客户2", "phone": ""
        })
        clue = r.json()

        past_time = (datetime.utcnow() - timedelta(days=2)).isoformat()
        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设置逾期",
            "stage_after": "contacted",
            "next_followup_at": past_time,
            "created_by": "测试"
        })
        client.post("/api/clues/check-overdue")

        r2 = client.get("/api/clues/overdue/list")
        assert r2.status_code == 200
        overdue = r2.json()
        assert any(c["id"] == clue["id"] for c in overdue), "逾期列表应包含逾期线索"

    def test_overdue_flag_on_clue_detail(self, client):
        r = client.post("/api/clues", json={
            "title": "逾期标记测试",
            "source": "其他", "region": "华中", "priority": "low",
            "customer_name": "逾期客户3", "phone": ""
        })
        clue = r.json()

        past_time = (datetime.utcnow() - timedelta(days=1)).isoformat()
        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设为逾期",
            "stage_after": "contacted",
            "next_followup_at": past_time,
            "created_by": "测试"
        })
        client.post("/api/clues/check-overdue")

        r2 = client.get(f"/api/clues/{clue['id']}")
        assert r2.json()["is_overdue"] is True, "线索详情应标记为逾期"

    def test_kanban_overdue_count_updates(self, client):
        r = client.post("/api/clues", json={
            "title": "看板逾期计数",
            "source": "其他", "region": "华中", "priority": "low",
            "customer_name": "逾期客户4", "phone": ""
        })
        clue = r.json()

        past_time = (datetime.utcnow() - timedelta(days=5)).isoformat()
        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设为逾期",
            "stage_after": "contacted",
            "next_followup_at": past_time,
            "created_by": "测试"
        })
        client.post("/api/clues/check-overdue")

        r2 = client.get("/api/kanban")
        assert r2.json()["overdue_count"] >= 1


class TestDailyReport:
    def test_daily_report_contains_summary(self, client):
        client.post("/api/clues", json={
            "title": "日报线索A",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "RA", "phone": ""
        })
        r = client.get("/api/reports/daily")
        assert r.status_code == 200
        report = r.json()
        assert "total_clues" in report
        assert "new_clues" in report
        assert "followed_up" in report
        assert "overdue_clues" in report
        assert "by_stage" in report
        assert "by_user" in report
        assert report["total_clues"] >= 1
        assert report["new_clues"] >= 1

    def test_daily_report_by_stage(self, client):
        client.post("/api/clues", json={
            "title": "阶段统计线索",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "RB", "phone": ""
        })
        r = client.get("/api/reports/daily")
        report = r.json()
        assert "new" in report["by_stage"]
        assert report["by_stage"]["new"] >= 1

    def test_daily_report_by_user(self, client):
        client.post("/api/clues", json={
            "title": "负责人统计线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "RC", "phone": ""
        })
        r = client.get("/api/reports/daily")
        report = r.json()
        assert len(report["by_user"]) >= 1
        for name, stats in report["by_user"].items():
            assert "total" in stats
            assert "followed" in stats
            assert "overdue" in stats

    def test_export_csv_contains_summary_and_details(self, client):
        client.post("/api/clues", json={
            "title": "导出CSV线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "RD", "phone": ""
        })
        r = client.get("/api/reports/daily/export")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        content = r.text
        assert "统计摘要" in content, "CSV应包含统计摘要"
        assert "按阶段统计" in content, "CSV应包含按阶段统计"
        assert "按负责人统计" in content, "CSV应包含按负责人统计"
        assert "线索明细" in content, "CSV应包含线索明细"
        assert "导出CSV线索" in content, "CSV线索明细应包含创建的线索"

    def test_export_csv_has_stage_and_overdue_columns(self, client):
        client.post("/api/clues", json={
            "title": "CSV字段测试",
            "source": "官网", "region": "华东", "priority": "medium",
            "customer_name": "RE", "phone": ""
        })
        r = client.get("/api/reports/daily/export")
        content = r.text
        lines = content.strip().split("\n")
        header_found = False
        for line in lines:
            if "阶段" in line and "是否逾期" in line:
                header_found = True
                break
        assert header_found, "CSV线索明细应有阶段和是否逾期列头"

    def test_daily_report_includes_clue_details(self, client):
        client.post("/api/clues", json={
            "title": "详情测试线索",
            "source": "转介绍", "region": "华南", "priority": "high",
            "customer_name": "RF", "phone": "13899998888"
        })
        r = client.get("/api/reports/daily")
        report = r.json()
        assert "clues" in report
        assert len(report["clues"]) >= 1
        clue = next(c for c in report["clues"] if c["title"] == "详情测试线索")
        assert clue["source"] == "转介绍"
        assert clue["region"] == "华南"
        assert clue["customer_name"] == "RF"


class TestReinitializationPersistence:
    def test_data_survives_reinit(self, file_db_path):
        db_url = f"sqlite:///{file_db_path}"

        test_app, engine1, session1 = _make_test_app(db_url)
        with TestClient(test_app) as c1:
            c1.post("/api/clues", json={
                "title": "持久化测试线索",
                "source": "官网", "region": "华北", "priority": "high",
                "customer_name": "P1", "phone": "13800001111"
            })
            c1.post("/api/clues", json={
                "title": "逾期持久化线索",
                "source": "其他", "region": "华中", "priority": "low",
                "customer_name": "P2", "phone": ""
            })
            clues_before = c1.get("/api/clues").json()
            overdue_clue_id = next(c["id"] for c in clues_before if c["title"] == "逾期持久化线索")
            past_time = (datetime.utcnow() - timedelta(days=3)).isoformat()
            c1.post(f"/api/clues/{overdue_clue_id}/followup", json={
                "content": "设置逾期跟进",
                "stage_after": "contacted",
                "next_followup_at": past_time,
                "created_by": "测试"
            })
            c1.post("/api/clues/check-overdue")

            clue_id = next(c["id"] for c in clues_before if c["title"] == "持久化测试线索")
            c1.post(f"/api/clues/{clue_id}/followup", json={
                "content": "持久化跟进记录",
                "stage_after": "qualified",
                "created_by": "测试"
            })
            original_assignee_id = next(c["assignee_id"] for c in clues_before if c["id"] == clue_id)
            other_user_id = 2 if original_assignee_id != 2 else 3
            c1.post(f"/api/clues/{clue_id}/reassign", json={"target_user_id": other_user_id})

        engine1.dispose()
        app.dependency_overrides.clear()

        test_app2, engine2, session2 = _make_test_app(db_url)
        with TestClient(test_app2) as c2:
            clues_after = c2.get("/api/clues").json()
            assert len(clues_after) >= 2, "重新初始化后线索应保留"

            persisted = next(c for c in clues_after if c["title"] == "持久化测试线索")
            assert persisted["assignee_id"] == other_user_id, "重新初始化后负责人应保留"
            assert persisted["stage"] == "qualified", "重新初始化后阶段应保留"

            detail = c2.get(f"/api/clues/{persisted['id']}").json()
            assert len(detail["followups"]) >= 1, "重新初始化后跟进记录应保留"
            assert any(f["content"] == "持久化跟进记录" for f in detail["followups"])

            overdue_clue = next(c for c in clues_after if c["title"] == "逾期持久化线索")
            assert overdue_clue["is_overdue"] is True, "重新初始化后逾期状态应保留"

            users = c2.get("/api/users").json()
            assert len(users) >= 4, "重新初始化后用户应保留"

            rules = c2.get("/api/assignment-rules").json()
            assert len(rules) >= 1, "重新初始化后分派规则应保留"

        engine2.dispose()
        app.dependency_overrides.clear()

    def test_fresh_init_creates_seed_data(self, file_db_path):
        db_url = f"sqlite:///{file_db_path}"

        test_app, engine, session = _make_test_app(db_url)
        with TestClient(test_app) as c:
            users = c.get("/api/users").json()
            assert len(users) == 4, "初始化应创建4个默认用户"
            names = [u["name"] for u in users]
            assert "张三" in names
            assert "李四" in names
            assert "王五" in names
            assert "赵六" in names

            rules = c.get("/api/assignment-rules").json()
            assert len(rules) >= 1, "初始化应创建默认分派规则"

        engine.dispose()
        app.dependency_overrides.clear()

    def test_init_idempotent_preserves_data(self, file_db_path):
        db_url = f"sqlite:///{file_db_path}"

        test_app1, engine1, _ = _make_test_app(db_url)
        with TestClient(test_app1) as c1:
            c1.post("/api/clues", json={
                "title": "幂等测试线索",
                "source": "官网", "region": "华北", "priority": "high",
                "customer_name": "IDEM", "phone": ""
            })

        app.dependency_overrides.clear()

        test_app2, engine2, _ = _make_test_app(db_url)
        with TestClient(test_app2) as c2:
            clues = c2.get("/api/clues").json()
            assert any(c["title"] == "幂等测试线索" for c in clues), "重复初始化不应丢失已有数据"
            users = c2.get("/api/users").json()
            assert len(users) == 4, "重复初始化不应重复创建用户"

        engine1.dispose()
        engine2.dispose()
        app.dependency_overrides.clear()


@pytest.fixture
def client_and_session():
    test_app, engine, session_factory = _make_test_app("sqlite://")
    with TestClient(test_app) as c:
        yield c, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


class TestOverdueAutoRefresh:
    def _make_overdue_candidate(self, client, session_factory):
        r = client.post("/api/clues", json={
            "title": "自动刷新逾期线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "AR", "phone": ""
        })
        clue = r.json()
        future_time = (datetime.utcnow() + timedelta(days=7)).isoformat()
        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设置未来跟进时间",
            "stage_after": "contacted",
            "next_followup_at": future_time,
            "created_by": "测试"
        })
        db = session_factory()
        try:
            db_clue = db.query(Clue).filter(Clue.id == clue["id"]).first()
            assert db_clue.is_overdue is False, "设置未来时间后不应逾期"
            past_time = datetime.utcnow() - timedelta(days=2)
            db_clue.next_followup_at = past_time
            db.commit()
        finally:
            db.close()
        return clue["id"]

    def test_kanban_auto_refreshes_overdue(self, client_and_session):
        client, session_factory = client_and_session
        clue_id = self._make_overdue_candidate(client, session_factory)
        r = client.get("/api/kanban")
        assert r.status_code == 200
        data = r.json()
        assert data["overdue_count"] >= 1, "看板应自动刷新逾期状态"
        all_clues = []
        for stage_clues in data["by_stage"].values():
            all_clues.extend(stage_clues)
        clue = next(c for c in all_clues if c["id"] == clue_id)
        assert clue["is_overdue"] is True

    def test_daily_report_auto_refreshes_overdue(self, client_and_session):
        client, session_factory = client_and_session
        clue_id = self._make_overdue_candidate(client, session_factory)
        r = client.get("/api/reports/daily")
        assert r.status_code == 200
        report = r.json()
        assert report["overdue_clues"] >= 1, "日报应自动刷新逾期状态"
        clue = next(c for c in report["clues"] if c["id"] == clue_id)
        assert clue["is_overdue"] is True

    def test_clue_detail_auto_refreshes_overdue(self, client_and_session):
        client, session_factory = client_and_session
        clue_id = self._make_overdue_candidate(client, session_factory)
        r = client.get(f"/api/clues/{clue_id}")
        assert r.status_code == 200
        assert r.json()["is_overdue"] is True, "线索详情应自动刷新逾期状态"

    def test_overdue_list_auto_refreshes(self, client_and_session):
        client, session_factory = client_and_session
        clue_id = self._make_overdue_candidate(client, session_factory)
        r = client.get("/api/clues/overdue/list")
        assert r.status_code == 200
        overdue = r.json()
        assert any(c["id"] == clue_id for c in overdue), "逾期列表应自动刷新包含新逾期线索"

    def test_auto_refresh_after_reinit(self, file_db_path):
        db_url = f"sqlite:///{file_db_path}"
        clue_id = None

        test_app, engine1, session1 = _make_test_app(db_url)
        with TestClient(test_app) as c1:
            r = c1.post("/api/clues", json={
                "title": "重启后自动刷新逾期",
                "source": "官网", "region": "华北", "priority": "high",
                "customer_name": "REINIT", "phone": ""
            })
            clue_id = r.json()["id"]
            future_time = (datetime.utcnow() + timedelta(days=7)).isoformat()
            c1.post(f"/api/clues/{clue_id}/followup", json={
                "content": "未来跟进",
                "stage_after": "contacted",
                "next_followup_at": future_time,
                "created_by": "测试"
            })
        engine1.dispose()
        app.dependency_overrides.clear()

        db = session1()
        try:
            db_clue = db.query(Clue).filter(Clue.id == clue_id).first()
            db_clue.next_followup_at = datetime.utcnow() - timedelta(days=1)
            db.commit()
        finally:
            db.close()

        test_app2, engine2, session2 = _make_test_app(db_url)
        with TestClient(test_app2) as c2:
            r = c2.get(f"/api/clues/{clue_id}")
            assert r.json()["is_overdue"] is True, "重启后详情应自动刷新逾期"
            r2 = c2.get("/api/kanban")
            assert r2.json()["overdue_count"] >= 1, "重启后看板应自动刷新逾期"
            r3 = c2.get("/api/clues/overdue/list")
            assert any(c["id"] == clue_id for c in r3.json()), "重启后逾期列表应自动刷新"
        engine2.dispose()
        app.dependency_overrides.clear()


class TestEndToEndFlow:
    def test_full_workflow(self, client):
        r = client.post("/api/clues", json={
            "title": "端到端流程线索",
            "source": "官网", "region": "华北", "priority": "high",
            "customer_name": "E2E", "phone": "13800000000"
        })
        clue = r.json()
        assert clue["assignee_name"] == "张三"
        assert clue["stage"] == "new"

        r2 = client.post(f"/api/clues/{clue['id']}/reassign", json={"target_user_id": clue["assignee_id"]})
        assert r2.status_code == 400

        r3 = client.post(f"/api/clues/{clue['id']}/reassign", json={"target_user_id": 2})
        assert r3.status_code == 200
        assert r3.json()["assignee_id"] == 2

        next_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r4 = client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "首次联系",
            "stage_after": "contacted",
            "next_followup_at": next_time,
            "created_by": "测试"
        })
        assert r4.status_code == 200

        r5 = client.get(f"/api/clues/{clue['id']}")
        detail = r5.json()
        assert detail["stage"] == "contacted"
        assert detail["last_followup_at"] is not None
        assert len(detail["followups"]) == 1

        past_time = (datetime.utcnow() - timedelta(days=2)).isoformat()
        client.post(f"/api/clues/{clue['id']}/followup", json={
            "content": "设为逾期",
            "stage_after": "qualified",
            "next_followup_at": past_time,
            "created_by": "测试"
        })
        client.post("/api/clues/check-overdue")

        r6 = client.get(f"/api/clues/{clue['id']}")
        assert r6.json()["is_overdue"] is True

        r7 = client.get("/api/reports/daily")
        report = r7.json()
        assert report["total_clues"] >= 1
        assert report["overdue_clues"] >= 1

        r8 = client.get("/api/reports/daily/export")
        csv_content = r8.text
        assert "端到端流程线索" in csv_content
        assert "统计摘要" in csv_content
