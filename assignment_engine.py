from sqlalchemy.orm import Session
from models import AssignmentRule, Clue, User
from typing import Optional, Tuple


def calculate_rule_score(rule: AssignmentRule, source: str, region: str, priority: str) -> int:
    score = 0
    if rule.source and rule.source == source:
        score += 100
    elif not rule.source:
        score += 30

    if rule.region and rule.region == region:
        score += 80
    elif not rule.region:
        score += 20

    if rule.priority and rule.priority == priority:
        score += 60
    elif not rule.priority:
        score += 15

    score -= rule.priority_order * 2
    return score


def auto_assign_clue(db: Session, clue: Clue) -> Tuple[Optional[User], Optional[str]]:
    if clue.assignee_id is not None:
        return None, f"线索已分派给 {clue.assignee.name}，拒绝重复分派"

    source = clue.source or ""
    region = clue.region or ""
    priority = clue.priority or ""

    rules = db.query(AssignmentRule).all()
    if not rules:
        return None, "没有配置分派规则"

    scored_rules = []
    for rule in rules:
        score = calculate_rule_score(rule, source, region, priority)
        scored_rules.append((score, rule))

    scored_rules.sort(key=lambda x: x[0], reverse=True)

    if scored_rules and scored_rules[0][0] > 0:
        top_rule = scored_rules[0][1]
        user = db.query(User).filter(User.id == top_rule.user_id).first()
        if user:
            return user, None

    return None, "没有匹配的分派规则"


def validate_reassign(db: Session, clue_id: int, target_user_id: int) -> Tuple[bool, str]:
    clue = db.query(Clue).filter(Clue.id == clue_id).first()
    if not clue:
        return False, "线索不存在"

    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        return False, "目标用户不存在"

    if clue.assignee_id == target_user_id:
        return False, f"该线索已由 {target_user.name} 负责，无需重复分派"

    return True, ""
