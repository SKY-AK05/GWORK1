from argparse import Namespace

from app.__main__ import _build_task


def test_company_research_brief_is_question_first_and_scope_complete():
    task = _build_task(Namespace(company="ORCHVATE", country="India", website=None, recent=None))
    assert "open company-identity question" in task
    assert "never merge on name similarity alone" in task
    assert "subsidiaries" in task and "branches" in task and "aliases" in task
    assert "customers" in task and "competitors" in task
    assert "recent joiners" in task and "departures" in task
    assert "remote/hybrid/office" in task
    assert "verified facts, secondary claims, inferences, and unknowns" in task
