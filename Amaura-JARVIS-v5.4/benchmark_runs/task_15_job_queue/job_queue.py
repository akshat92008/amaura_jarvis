import uuid
from typing import Any, Callable, Dict, Tuple

class JobQueue:
    def __init__(self):
        self.jobs: Dict[str, Tuple[Callable, Tuple, Dict, str]] = {}
        self.results: Dict[str, Any] = {}
        self.errors: Dict[str, Exception] = {}

    def enqueue(self, func: Callable, *args, **kwargs) -> str:
        """Enqueue a job and return its job_id."""
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = (func, args, kwargs, 'pending')
        return job_id

    def run_next(self) -> Any:
        """Run the next pending job and return its result."""
        for job_id, (func, args, kwargs, status) in self.jobs.items():
            if status == 'pending':
                try:
                    result = func(*args, **kwargs)
                    self.results[job_id] = result
                    self.jobs[job_id] = (func, args, kwargs, 'completed')
                    return result
                except Exception as e:
                    self.errors[job_id] = e
                    self.jobs[job_id] = (func, args, kwargs, 'failed')
                    raise
        raise ValueError("No pending jobs in queue")

    def get_status(self, job_id: str) -> str:
        """Get the status of a job."""
        if job_id not in self.jobs:
            raise ValueError(f"Job {job_id} not found")
        return self.jobs[job_id][3]

    def get_result(self, job_id: str) -> Any:
        """Get the result of a completed job."""
        if job_id not in self.results:
            raise ValueError(f"Result for job {job_id} not found")
        return self.results[job_id]

    def get_error(self, job_id: str) -> Exception:
        """Get the error of a failed job."""
        if job_id not in self.errors:
            raise ValueError(f"Error for job {job_id} not found")
        return self.errors[job_id]
