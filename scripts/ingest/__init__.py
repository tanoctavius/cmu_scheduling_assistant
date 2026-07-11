"""Self-owned ingestion for cmu-scheduler.

We parse official CMU sources ourselves (Schedule of Classes, Course Catalog) and
a manual FCE export into the Stage 1 models. No hosted API, no dependency on the
abandoned 2019 ``cmu_course_api`` package. See README.md in this directory.
"""
