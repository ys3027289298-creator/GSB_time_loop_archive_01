"""时间循环档案馆：8 个循环状态 bug 的回归测试 + 首次循环边界。"""

import json
import os
import tempfile
import unittest

from archive.core import Game, SEED, TIMELINES, MAX_LOOPS, CLUES, EVENTS


class TimeLoopBugFixTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()

    def test_loop_reset_keeps_unlocked_clues(self):
        # Bug 1：循环重置遗漏已解锁线索 —— 回溯/重置后线索必须保留。
        self.game.set_checkpoint()
        self.game.explore()  # 解锁 clock_key
        self.assertIn("clock_key", self.game.unlocked_clues)

        self.game.rewind()  # 进入循环 2，临时状态重置

        self.assertIn("clock_key", self.game.unlocked_clues,
                      "已解锁线索属于永久状态，循环重置后必须保留")
        self.assertEqual(self.game.event_pointer, 0)

    def test_same_clue_scores_once_across_loops(self):
        # Bug 2：同一线索跨循环重复加分 —— 只在首次解锁时计分。
        self.game.set_checkpoint()
        self.game.explore()  # clock_key +10
        score_after_first = self.game.score

        self.assertEqual(score_after_first, 10)

        self.game.rewind()
        self.game.explore()  # 再次发现 clock_key

        self.assertEqual(self.game.score, score_after_first,
                         "同一线索跨循环重复发现不得再次加分")
        self.assertIn("clock_key", self.game.unlocked_clues)

    def test_rewind_restores_event_pointer_to_checkpoint(self):
        # Bug 3：回溯后事件指针必须回到检查点。
        self.game.explore()
        self.game.explore()
        self.assertEqual(self.game.event_pointer, 2)
        self.game.set_checkpoint()  # 检查点 = 2
        self.game.explore()
        self.assertEqual(self.game.event_pointer, 3)

        self.game.rewind()

        self.assertEqual(self.game.event_pointer, 2,
                         "回溯后事件指针必须精确回到检查点")

    def test_character_memory_cleared_at_correct_phase(self):
        # Bug 4：角色记忆只在进入新循环（循环重置）时清空，
        # 探索、存档/读档都不应清空。
        self.game.talk("archivist", "第一次交谈")
        self.assertTrue(self.game.memories)
        snapshot = self.game.to_snapshot()

        reloaded = Game().load_snapshot(snapshot)
        self.assertTrue(reloaded.memories, "读档不应清空角色记忆")

        reloaded.set_checkpoint()
        reloaded.rewind()
        self.assertEqual(reloaded.memories, {},
                         "记忆只能在循环重置（进入新循环）阶段清空")
        # 永久状态仍然完整。
        self.assertIsNotNone(reloaded.checkpoint)

    def test_completion_only_after_all_timelines_verified(self):
        # Bug 5：未验证全部时间线前，完成结局不得触发。
        for _ in EVENTS:
            self.game.explore()

        for timeline in TIMELINES[:-1]:
            self.game.verify(timeline)
            self.assertFalse(
                self.game.finished,
                "只验证部分时间线时不得触发完成结局")
            self.assertIsNone(self.game.ending)

        self.game.verify(TIMELINES[-1])
        self.assertTrue(self.game.finished)
        self.assertEqual(self.game.ending, "true_ending")

    def test_verify_rejected_when_clues_missing(self):
        # 边界：线索不齐不能验证时间线。
        output = self.game.verify("alpha")
        self.assertNotIn("alpha", self.game.verified_timelines)
        self.assertIn("缺少", output)

    def test_snapshot_excludes_loop_temporary_items(self):
        # Bug 6：保存快照不得包含当前循环的临时物品。
        self.game.explore()  # 拾取 candle
        self.assertTrue(self.game.temp_items)

        data = self.game.to_snapshot()
        self.assertNotIn("temp_items", data,
                         "临时物品不能写入 JSON 快照")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "save.json")
            self.game.save(path)
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle)
            self.assertNotIn("temp_items", raw)

            loaded = Game()
            loaded.load(path)
        self.assertEqual(loaded.temp_items, [],
                         "读档后当前循环必须从空临时物品开始")
        # 永久状态完整恢复。
        self.assertIn("clock_key", loaded.unlocked_clues)
        self.assertEqual(loaded.score, self.game.score)

    def test_load_does_not_reapply_permanent_upgrades(self):
        # Bug 7：加载快照不能重复应用永久升级（lantern 只 +5 一次）。
        self.game.explore()
        self.game.explore()
        self.game.explore()  # mirror_hall 事件授予 lantern
        self.assertIn("lantern", self.game.upgrades)
        score_with_upgrade = self.game.score

        snapshot = self.game.to_snapshot()
        loaded = Game().load_snapshot(snapshot)
        self.assertEqual(loaded.score, score_with_upgrade,
                         "读档不能重复结算永久升级")
        loaded_again = Game().load_snapshot(loaded.to_snapshot())
        self.assertEqual(loaded_again.score, score_with_upgrade)
        self.assertEqual(loaded_again.upgrades, {"lantern"})

    def test_illegal_rewind_does_not_consume_loop(self):
        # Bug 8：非法回溯（无检查点）不得消耗循环次数，也不得移动指针。
        self.assertEqual(self.game.loop_count, 1)
        output = self.game.rewind()
        self.assertIn("无法回溯", output)
        self.assertEqual(self.game.loop_count, 1,
                         "非法回溯不能增加循环次数")
        self.assertEqual(self.game.event_pointer, 0)
        self.assertEqual(self.game.temp_items, [])

    def test_illegal_rewind_after_loop_budget_exhausted(self):
        # 达到 MAX_LOOPS 后回溯同样非法且不改动状态。
        self.game.checkpoint = 0
        self.game.loop_count = MAX_LOOPS
        output = self.game.rewind()
        self.assertIn("无法回溯", output)
        self.assertEqual(self.game.loop_count, MAX_LOOPS)

    def test_first_loop_boundary(self):
        # 首次循环边界：循环号从 1 开始，无检查点，临时状态为空，
        # 无结局，固定种子下首次探索完全可重复。
        fresh = Game()
        self.assertEqual(fresh.seed, SEED)
        self.assertEqual(fresh.loop_count, 1)
        self.assertEqual(fresh.event_pointer, 0)
        self.assertIsNone(fresh.checkpoint)
        self.assertEqual(fresh.temp_items, [])
        self.assertEqual(fresh.memories, {})
        self.assertEqual(fresh.unlocked_clues, set())
        self.assertEqual(fresh.verified_timelines, set())
        self.assertIsNone(fresh.ending)
        self.assertFalse(fresh.finished)

        first = Game().explore()
        second = Game().explore()
        self.assertEqual(first, second, "固定种子要求首次探索输出可重复")

        # 首次循环无检查点时，rewind 是非法回溯。
        boundary = Game()
        self.assertIn("无法回溯", boundary.rewind())
        self.assertEqual(boundary.loop_count, 1)
        # 合法回溯后循环号严格 +1。
        boundary.set_checkpoint()
        boundary.rewind()
        self.assertEqual(boundary.loop_count, 2)

    def test_full_loop_cycle_is_reproducible(self):
        # 端到端：探索 → 检查点 → 跨循环重复线索 → 存档读档 → 验证时间线，
        # 整条路径状态分离清晰、结果可重复。
        game = Game()
        game.set_checkpoint()
        for _ in EVENTS:
            game.explore()
        temp_items_loop_one = list(game.temp_items)
        self.assertTrue(temp_items_loop_one)
        game.rewind()

        self.assertEqual(game.event_pointer, 0)
        self.assertEqual(game.loop_count, 2)
        self.assertEqual(game.temp_items, [])
        self.assertEqual(game.memories, {})
        score_before = game.score
        for _ in EVENTS:
            game.explore()
        # 第二次走完相同事件：线索都已计过分，升级在循环 1 已获得，
        # 本次不重复授予，分数保持不变。
        self.assertEqual(game.score, score_before)

        for timeline in TIMELINES:
            game.verify(timeline)
        self.assertTrue(game.finished)

        replayed = Game().load_snapshot(game.to_snapshot())
        self.assertEqual(replayed.score, game.score)
        self.assertEqual(replayed.verified_timelines, set(TIMELINES))
        self.assertEqual(replayed.ending, "true_ending")
        self.assertEqual(replayed.temp_items, [])


if __name__ == "__main__":
    unittest.main()
