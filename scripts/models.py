from __future__ import annotations

import hashlib
from dataclasses import dataclass


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
