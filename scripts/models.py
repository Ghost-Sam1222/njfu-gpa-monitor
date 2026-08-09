from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Exam:
    semester: str
    exam_project_id: str
    exam_project_name: str
    exam_type: str
    campus: str
    course_code: str
    course_name: str
    start_time: datetime
    end_time: datetime
    location: str

    def stable_key(self) -> str:
        """A dedup key independent of project name (which may vary by display)."""
        payload = "|".join(
            (
                self.semester,
                self.course_code,
                self.course_name,
                self.start_time.isoformat(),
                self.end_time.isoformat(),
                self.location,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Grade:
    semester: str
    course_code: str
    course_name: str
    score: str
    credit: str
    gpa: str
    course_type: str

    def identity(self, salt: str) -> str:
        payload = "|".join(
            (
                salt,
                self.semester,
                self.course_code,
                self.course_name,
                self.score,
                self.credit,
                self.gpa,
                self.course_type,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
