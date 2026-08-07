class AppError(Exception):
    code = "application_error"
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidRepositoryUrl(AppError):
    code = "invalid_repository_url"
    status_code = 422


class RepositoryNotFound(AppError):
    code = "repository_not_found"
    status_code = 404


class GitHubRateLimited(AppError):
    code = "github_rate_limited"
    status_code = 429


class RepositoryTooLarge(AppError):
    code = "repository_too_large"
    status_code = 413


class UnsupportedProject(AppError):
    code = "unsupported_project"
    status_code = 422


class AnalysisFailed(AppError):
    code = "analysis_failed"
    status_code = 500


class AnalysisNotFound(AppError):
    code = "analysis_not_found"
    status_code = 404


class IncompatibleAnalysisVersions(AppError):
    code = "incompatible_analysis_versions"
    status_code = 409


class ReportNotReady(AppError):
    code = "report_not_ready"
    status_code = 409


class InvalidComparison(AppError):
    code = "invalid_comparison"
    status_code = 422
