from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

Base = declarative_base()

class WorkItem(Base):
    __tablename__ = 'work_items'

    id = Column(String, primary_key=True)
    parent_id = Column(String, ForeignKey('work_items.id'))
    item_type = Column(String, nullable=False)
    workflow_id = Column(String)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False, default='')
    owner_id = Column(String, nullable=False)
    reviewer_id = Column(String)
    state = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=3)
    deadline = Column(String)
    budget_cents = Column(Integer, nullable=False, default=0)
    spent_cents = Column(Integer, nullable=False, default=0)
    risk = Column(String, nullable=False, default='low')
    action_type = Column(String, nullable=False, default='internal_work')
    success_metric = Column(String, nullable=False, default='')
    acceptance_criteria = Column(Text, nullable=False, default='[]')
    dependencies = Column(Text, nullable=False, default='[]')
    evidence = Column(Text, nullable=False, default='[]')
    summary = Column(String, nullable=False, default='')
    metadata = Column(Text, nullable=False, default='{}')
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

class Approval(Base):
    __tablename__ = 'approvals'

    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey('work_items.id'), nullable=False)
    action_type = Column(String, nullable=False)
    risk = Column(String, nullable=False)
    status = Column(String, nullable=False)
    requested_by = Column(String, nullable=False)
    decided_by = Column(String)
    reason = Column(String, nullable=False, default='')
    payload = Column(Text, nullable=False, default='{}')
    payload_hash = Column(String, nullable=False, default='')
    created_at = Column(String, nullable=False)
    expires_at = Column(String)
    resolved_at = Column(String)

class Campaign(Base):
    __tablename__ = 'campaigns'

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    target_segment = Column(String, nullable=False)
    offer = Column(String, nullable=False)
    minimum_score = Column(Integer, nullable=False, default=70)
    active = Column(Integer, nullable=False, default=1)
    daily_lead_limit = Column(Integer, nullable=False, default=10)
    daily_outreach_limit = Column(Integer, nullable=False, default=3)
    daily_followup_limit = Column(Integer, nullable=False, default=5)
    maximum_followups = Column(Integer, nullable=False, default=2)
    config = Column(Text, nullable=False, default='{}')
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

class Lead(Base):
    __tablename__ = 'leads'

    id = Column(String, primary_key=True)
    campaign_id = Column(String, ForeignKey('campaigns.id'), nullable=False)
    company_name = Column(String, nullable=False)
    domain = Column(String, nullable=False, unique=True)
    contact_name = Column(String, nullable=False, default='')
    public_contact = Column(String, nullable=False, default='')
    contact_source_url = Column(String, nullable=False, default='')
    linkedin_url = Column(String, nullable=False, default='')
    country = Column(String, nullable=False, default='')
    industry = Column(String, nullable=False, default='')
    stage = Column(String, nullable=False, default='discovered')
    total_score = Column(Integer, nullable=False, default=0)
    score_components = Column(Text, nullable=False, default='{}')
    do_not_contact = Column(Integer, nullable=False, default=0)
    opt_out_reason = Column(String, nullable=False, default='')
    estimated_value_cents = Column(Integer, nullable=False, default=0)
    next_action = Column(String, nullable=False, default='')
    next_action_at = Column(String)
    metadata = Column(Text, nullable=False, default='{}')
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

class Message(Base):
    __tablename__ = 'messages'

    id = Column(String, primary_key=True)
    lead_id = Column(String, ForeignKey('leads.id'), nullable=False)
    channel = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    subject = Column(String, nullable=False, default='')
    body = Column(String, nullable=False)
    recipient = Column(String, nullable=False, default='')
    approved_payload_hash = Column(String, nullable=False, default='')
    status = Column(String, nullable=False, default='draft')
    approved_by = Column(String)
    approved_at = Column(String)
    sent_at = Column(String)
    external_message_id = Column(String, unique=True)
    thread_id = Column(String)
    idempotency_key = Column(String, nullable=False, unique=True)
    evidence_snapshot = Column(Text, nullable=False, default='[]')
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

def get_engine(db_url: str):
    return create_engine(db_url)

def get_session_factory(engine):
    return sessionmaker(bind=engine)
