# TargetHub Technology Stack

> This document defines the official technology stack used throughout the TargetHub project.
>
> Any proposal to replace or introduce a new technology should be discussed and documented through an ADR (Architecture Decision Record).

---

# Backend

| Category | Technology | Status | Notes |
|----------|------------|--------|------|
| Language | Python 3.12+ | ✅ | Primary backend language |
| Framework | FastAPI | ✅ | REST API framework |
| Package Manager | uv | ✅ | Dependency and environment management |
| ASGI Server | Uvicorn | ✅ | Development server |
| Configuration | Pydantic Settings | ✅ | Environment configuration |
| Logging | Loguru | ✅ | Structured logging |
| Validation | Pydantic v2 | ✅ | Data validation |

---

# Database

| Category | Technology | Status | Notes |
|----------|------------|--------|------|
| ORM | SQLAlchemy 2.x | ✅ | Database ORM |
| Migrations | Alembic | ✅ | Schema migrations |
| Development DB | SQLite | ✅ | Local development |
| Production DB | PostgreSQL | Planned | Production deployment |

---

# Frontend

| Category | Technology | Status |
|----------|------------|--------|
| Language | TypeScript | Planned |
| Framework | React | Planned |
| Build Tool | Vite | Planned |
| UI Library | Material UI | Planned |
| State Management | TBD | Planned |

---

# Desktop Integration

| Category | Technology | Status |
|----------|------------|--------|
| IDE | VS Code | Planned |
| Extension API | VS Code Extension API | Planned |

---

# APIs

| Category | Technology | Status |
|----------|------------|--------|
| REST | FastAPI | ✅ |
| OpenAPI | Swagger | ✅ |
| WebSockets | FastAPI | Planned |

---

# Authentication

| Category | Technology | Status |
|----------|------------|--------|
| Authentication | JWT | Planned |
| Password Hashing | Passlib | Planned |
| OAuth | TBD | Future |

---

# Testing

| Category | Technology | Status |
|----------|------------|--------|
| Unit Testing | Pytest | ✅ |
| HTTP Testing | HTTPX | ✅ |
| Coverage | Coverage.py | Planned |

---

# Code Quality

| Category | Technology | Status |
|----------|------------|--------|
| Formatter | Black | ✅ |
| Linter | Ruff | ✅ |
| Import Sorting | isort | ✅ |
| Pre-commit | pre-commit | Planned |

---

# Documentation

| Category | Technology | Status |
|----------|------------|--------|
| Documentation | MkDocs Material | ✅ |
| Architecture Decisions | ADR | ✅ |
| Feature Proposals | RFC | ✅ |

---

# DevOps

| Category | Technology | Status |
|----------|------------|--------|
| Containerization | Docker | Planned |
| CI/CD | GitHub Actions | Planned |

---

# Hardware Integrations

| Category | Technology | Status |
|----------|------------|--------|
| Serial Access | Plugin | Planned |
| Power Control | REST Provider | Planned |
| J-Link Debugging | Plugin | Planned |
| SSH/Telnet | Proxy Provider | Planned |
| FTP/SFTP | Deployment Provider | Planned |

---

# Guiding Principles

- Keep dependencies minimal.
- Prefer mature and well-supported libraries.
- Avoid introducing multiple libraries that solve the same problem.
- Every new technology must be justified through an ADR.
- TargetHub should remain modular and plugin-oriented.
