import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class RepositoryORM(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repository_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    html_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    analyses: Mapped[list["AnalysisORM"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class AnalysisORM(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "commit_sha", "analyzer_version", name="uq_analysis_identity"
        ),
        Index("ix_analysis_repository_created", "repository_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(30), nullable=False)
    framework: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    score: Mapped[float | None] = mapped_column(Float)
    maturity: Mapped[str | None] = mapped_column(String(50))
    coverage: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[RepositoryORM] = relationship(back_populates="analyses")
    categories: Mapped[list["CategoryResultORM"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    checks: Mapped[list["CheckResultORM"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class CategoryResultORM(Base):
    __tablename__ = "category_results"
    __table_args__ = (UniqueConstraint("analysis_id", "category", name="uq_analysis_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    applicable_points: Mapped[float] = mapped_column(Float, nullable=False)
    registry_points: Mapped[float] = mapped_column(Float, nullable=False)

    analysis: Mapped[AnalysisORM] = relationship(back_populates="categories")


class CheckResultORM(Base):
    __tablename__ = "check_results"
    __table_args__ = (UniqueConstraint("analysis_id", "check_id", name="uq_analysis_check"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    points: Mapped[float] = mapped_column(Float, nullable=False)
    max_points: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    analysis: Mapped[AnalysisORM] = relationship(back_populates="checks")
    evidence: Mapped[list["EvidenceORM"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )
    recommendation: Mapped["RecommendationORM | None"] = relationship(
        back_populates="check", cascade="all, delete-orphan", uselist=False
    )


class EvidenceORM(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_result_id: Mapped[int] = mapped_column(
        ForeignKey("check_results.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)

    check: Mapped[CheckResultORM] = relationship(back_populates="evidence")


class RecommendationORM(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_result_id: Mapped[int] = mapped_column(
        ForeignKey("check_results.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    check: Mapped[CheckResultORM] = relationship(back_populates="recommendation")
