# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from _common import APP  # noqa: F401
import teams


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_teams = teams.TEAMS_FILE
        self.old_prompts = teams.PROMPTS_FILE
        self.old_cache = dict(teams._CACHE)
        self.old_pcache = dict(teams._PROMPTS)
        teams.TEAMS_FILE = os.path.join(self.td.name, "teams.json")
        teams.PROMPTS_FILE = os.path.join(self.td.name, "team_prompts.json")
        teams._CACHE.update({"mtime": 0.0, "data": None})
        teams._PROMPTS.update({"mtime": 0.0, "data": None})

    def tearDown(self):
        teams.TEAMS_FILE = self.old_teams
        teams.PROMPTS_FILE = self.old_prompts
        teams._CACHE.update(self.old_cache)
        teams._PROMPTS.update(self.old_pcache)
        self.td.cleanup()

    def test_members_and_roles(self):
        team = teams.create_team("工作室", "u_owner")
        tid = team["id"]
        self.assertEqual(teams.role_of("u_owner", tid), "owner")
        teams.add_member(tid, "u_editor", "editor")
        teams.add_member(tid, "u_viewer", "viewer")
        self.assertTrue(teams.can_view("u_viewer", tid))
        self.assertFalse(teams.can_edit("u_viewer", tid))
        self.assertTrue(teams.can_edit("u_editor", tid))
        self.assertFalse(teams.can_manage("u_editor", tid))
        self.assertTrue(teams.can_manage("u_owner", tid))
        self.assertEqual(teams.shared_uids("u_editor"),
                         {"u_editor", "u_owner", "u_viewer"})
        self.assertTrue(teams.share_owner("u_viewer", "u_owner"))
        self.assertFalse(teams.share_owner("u_outsider", "u_owner"))

    def test_owner_cannot_be_removed(self):
        team = teams.create_team("项目", "u_owner")
        tid = team["id"]
        with self.assertRaises(ValueError):
            teams.remove_member(tid, "u_owner")
        with self.assertRaises(ValueError):
            teams.set_role(tid, "u_owner", "viewer")

    def test_shared_prompts_permissions(self):
        team = teams.create_team("项目", "u_owner")
        tid = team["id"]
        teams.add_member(tid, "u_editor", "editor")
        teams.add_member(tid, "u_viewer", "viewer")
        item = teams.add_prompt(tid, "雨后的青石巷", by="u_editor")
        self.assertEqual(len(teams.list_prompts(tid)), 1)
        with self.assertRaises(ValueError):
            teams.delete_prompt(tid, item["id"], uid="u_viewer")
        teams.delete_prompt(tid, item["id"], uid="u_editor")
        self.assertEqual(teams.list_prompts(tid), [])

    def test_list_for_user_and_delete(self):
        a = teams.create_team("A", "u_a")
        teams.create_team("B", "u_b")
        rows = teams.list_for_user("u_a")
        self.assertEqual([x["id"] for x in rows], [a["id"]])
        teams.delete_team(a["id"])
        self.assertEqual(teams.list_for_user("u_a"), [])


if __name__ == "__main__":
    unittest.main()
