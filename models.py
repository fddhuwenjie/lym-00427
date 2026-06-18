from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./clue_kanban.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    assigned_clues = relationship("Clue", back_populates="assignee", foreign_keys="Clue.assignee_id")
    rules = relationship("AssignmentRule", back_populates="user")


class AssignmentRule(Base):
    __tablename__ = "assignment_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    source = Column(String(100), default="")
    region = Column(String(100), default="")
    priority = Column(String(20), default="")
    priority_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="rules")


class Clue(Base):
    __tablename__ = "clues"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    customer_name = Column(String(200), default="")
    phone = Column(String(50), default="")
    source = Column(String(100), default="")
    region = Column(String(100), default="")
    priority = Column(String(20), default="medium")
    stage = Column(String(50), default="new")
    status = Column(String(20), default="active")
    description = Column(Text, default="")
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_followup_at = Column(DateTime, nullable=True)
    next_followup_at = Column(DateTime, nullable=True)
    is_overdue = Column(Boolean, default=False)

    assignee = relationship("User", back_populates="assigned_clues", foreign_keys=[assignee_id])
    followups = relationship("FollowupRecord", back_populates="clue", order_by="desc(FollowupRecord.created_at)")


class FollowupRecord(Base):
    __tablename__ = "followup_records"

    id = Column(Integer, primary_key=True, index=True)
    clue_id = Column(Integer, ForeignKey("clues.id"), nullable=False)
    content = Column(Text, nullable=False)
    stage_after = Column(String(50), default="")
    next_followup_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    clue = relationship("Clue", back_populates="followups")


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            users = [
                User(name="张三", email="zhangsan@example.com"),
                User(name="李四", email="lisi@example.com"),
                User(name="王五", email="wangwu@example.com"),
                User(name="赵六", email="zhaoliu@example.com"),
            ]
            db.add_all(users)
            db.flush()

            rules = [
                AssignmentRule(user_id=1, source="官网", region="华北", priority="high", priority_order=1),
                AssignmentRule(user_id=1, source="官网", region="华北", priority="medium", priority_order=2),
                AssignmentRule(user_id=2, source="官网", region="华东", priority="high", priority_order=1),
                AssignmentRule(user_id=2, source="官网", region="华东", priority="medium", priority_order=2),
                AssignmentRule(user_id=3, source="转介绍", region="", priority="high", priority_order=1),
                AssignmentRule(user_id=3, source="转介绍", region="", priority="medium", priority_order=2),
                AssignmentRule(user_id=4, source="", region="", priority="low", priority_order=1),
                AssignmentRule(user_id=4, source="", region="", priority="", priority_order=10),
            ]
            db.add_all(rules)
            db.commit()
    finally:
        db.close()
