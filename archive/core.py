"""时间循环档案馆 —— 核心逻辑。

状态分层（严格分离，互不混淆）：

* 永久状态：unlocked_clues / scored_clues / score / verified_timelines /
  upgrades —— 跨循环保留，循环重置与回溯都不会清除。
* 循环临时状态：temp_items / memories —— 仅属于当前循环，只在进入新循环
  （回溯触发循环重置）时清空。
* 检查点：checkpoint —— 回溯时事件指针的恢复位置。
* 循环次数：loop_count —— 首次进入档案馆即为循环 1，只有合法回溯才 +1。
* 事件指针：event_pointer —— 指向 EVENTS 中的下一个事件。
* 结局：ending / finished —— 仅在全部时间线验证完成后置位。

对外保留：CMD 菜单、固定种子 SEED、JSON 快照存档、命令行命令格式。
仅使用标准库。
"""

import json
import random

SEED = 58
MAX_LOOPS = 8
SAVE_VERSION = 1

TIMELINES = ("alpha", "beta", "gamma")

# 线索：每条线索属于一条时间线，只在全局第一次解锁时计分一次。
CLUES = {
    "clock_key": {"timeline": "alpha", "points": 10},
    "ash_letter": {"timeline": "alpha", "points": 10},
    "mirror_map": {"timeline": "beta", "points": 20},
    "silent_bell": {"timeline": "beta", "points": 20},
    "last_page": {"timeline": "gamma", "points": 40},
}

# 永久升级：效果只在获得时应用一次，读档恢复集合但绝不重复应用效果。
UPGRADES = {
    "lantern": {"bonus_score": 5},
}

# 档案馆事件按固定顺序排列，event_pointer 指向其中一项。
EVENTS = [
    {"id": "foyer",       "name": "门厅",       "clue": "clock_key",
     "item": "candle",    "memory": "archivist"},
    {"id": "study",       "name": "档案室",     "clue": "ash_letter",
     "item": None,        "memory": "archivist"},
    {"id": "mirror_hall", "name": "镜廊",       "clue": "mirror_map",
     "item": None,        "memory": None, "upgrade": "lantern"},
    {"id": "bell_tower",  "name": "钟楼",       "clue": "silent_bell",
     "item": None,        "memory": "bell_keeper"},
    {"id": "sealed_room", "name": "封印之室",   "clue": "last_page",
     "item": "seal_ink",  "memory": "bell_keeper"},
]

MENU = """\
=== 时间循环档案馆 ===
explore            探索当前事件
talk <角色>        与角色交谈（在当前循环留下记忆）
checkpoint         在当前事件位置设置检查点
rewind             回溯到检查点（合法时进入下一循环）
verify <时间线>    验证时间线 (alpha / beta / gamma)
save <路径>        保存 JSON 快照
load <路径>        加载 JSON 快照
status             查看当前状态
help               显示菜单
quit               离开档案馆"""


class Game:
    def __init__(self, seed=SEED):
        self.seed = seed

        # ---- 永久状态（跨循环保留）----
        self.unlocked_clues = set()      # 已解锁线索
        self.scored_clues = set()        # 已计过分的线索（与解锁集合分开记账）
        self.score = 0
        self.verified_timelines = set()
        self.upgrades = set()

        # ---- 循环临时状态（仅属于当前循环）----
        self.temp_items = []
        self.memories = {}

        # ---- 检查点 / 循环次数 / 事件指针 ----
        self.checkpoint = None
        self.loop_count = 1
        self.event_pointer = 0

        # ---- 结局 ----
        self.ending = None
        self.finished = False

    # ------------------------------------------------------------------
    # 内部状态操作
    # ------------------------------------------------------------------
    def _unlock_clue(self, clue_id):
        """解锁线索；同一条线索全局只计分一次，跨循环重复发现不再加分。"""
        self.unlocked_clues.add(clue_id)
        if clue_id in self.scored_clues:
            return "再次发现线索：{}（跨循环保留，不再加分）".format(clue_id)
        self.scored_clues.add(clue_id)
        points = CLUES[clue_id]["points"]
        self.score += points
        return "解锁线索：{}（+{} 分）".format(clue_id, points)

    def _apply_upgrade(self, upgrade_id):
        """获得永久升级；效果只在这里应用一次，读档不会重新应用。"""
        if upgrade_id in self.upgrades:
            return ""
        self.upgrades.add(upgrade_id)
        self.score += UPGRADES[upgrade_id]["bonus_score"]
        return "获得永久升级：{}（+{} 分）".format(
            upgrade_id, UPGRADES[upgrade_id]["bonus_score"])

    def _reset_loop_state(self):
        """循环重置：清空当前循环的临时物品与角色记忆。

        永久状态（线索、分数、升级、已验证时间线）一律不动。
        """
        self.temp_items = []
        self.memories = {}

    def _echo_code(self):
        """基于固定种子、循环次数、事件位置生成确定性回声编号。"""
        rng = random.Random(
            self.seed * 1000003 + self.loop_count * 1009 + self.event_pointer)
        return rng.randrange(100000, 999999)

    # ------------------------------------------------------------------
    # 游戏动作
    # ------------------------------------------------------------------
    def explore(self):
        if self.event_pointer >= len(EVENTS):
            return "档案馆深处一片寂静，已没有可探索的事件。"
        event = EVENTS[self.event_pointer]
        self.event_pointer += 1
        messages = [
            "回声 #{}：循环 {} · 探索「{}」".format(
                self._echo_code(), self.loop_count, event["name"])]
        messages.append(self._unlock_clue(event["clue"]))
        if event.get("item"):
            self.temp_items.append(event["item"])
            messages.append("拾取临时物品：{}".format(event["item"]))
        if event.get("memory"):
            self.memories[event["memory"]] = "在{}相遇".format(event["name"])
        if event.get("upgrade"):
            upgrade_msg = self._apply_upgrade(event["upgrade"])
            if upgrade_msg:
                messages.append(upgrade_msg)
        return "\n".join(messages)

    def talk(self, character, note=""):
        self.memories[character] = note or "一段关于档案馆的交谈"
        return "{} 的记忆已记入当前循环（共 {} 条）".format(
            character, len(self.memories))

    def set_checkpoint(self):
        self.checkpoint = self.event_pointer
        return "检查点已设置在事件位置 {}。".format(self.checkpoint)

    def rewind(self):
        """回溯到检查点。非法回溯（无检查点/循环耗尽）不消耗循环次数。"""
        if self.checkpoint is None:
            return "无法回溯：尚未设置检查点（循环次数保持 {}）。".format(
                self.loop_count)
        if self.loop_count >= MAX_LOOPS:
            return "无法回溯：循环次数已耗尽（剩余 0）。"
        self.event_pointer = self.checkpoint
        self.loop_count += 1
        self._reset_loop_state()
        return "回溯完成：事件指针回到 {}，进入循环 {}。".format(
            self.checkpoint, self.loop_count)

    def verify(self, timeline):
        if timeline not in TIMELINES:
            return "未知时间线：{}".format(timeline)
        if timeline in self.verified_timelines:
            return "时间线 {} 已经验证过。".format(timeline)
        needed = {c for c, meta in CLUES.items()
                  if meta["timeline"] == timeline}
        if not needed <= self.unlocked_clues:
            missing = sorted(needed - self.unlocked_clues)
            return "时间线 {} 的线索尚未集齐，无法验证（缺少：{}）。".format(
                timeline, ", ".join(missing))
        self.verified_timelines.add(timeline)
        if set(TIMELINES) <= self.verified_timelines:
            self.ending = "true_ending"
            self.finished = True
            return ("全部 {} 条时间线验证完成，真结局开启：{}。".format(
                len(TIMELINES), self.ending))
        return "时间线 {} 验证完成（已验证 {}/{}）。".format(
            timeline, len(self.verified_timelines), len(TIMELINES))

    def status(self):
        return "\n".join([
            "--- 档案馆状态 ---",
            "循环：{}/{}  事件指针：{}/{}  检查点：{}".format(
                self.loop_count, MAX_LOOPS, self.event_pointer,
                len(EVENTS),
                self.checkpoint if self.checkpoint is not None else "无"),
            "分数：{}  已解锁线索：{}".format(
                self.score, ", ".join(sorted(self.unlocked_clues)) or "无"),
            "已验证时间线：{}  永久升级：{}".format(
                ", ".join(sorted(self.verified_timelines)) or "无",
                ", ".join(sorted(self.upgrades)) or "无"),
            "临时物品：{}  记忆：{} 条".format(
                ", ".join(self.temp_items) or "无", len(self.memories)),
            "结局：{}".format(self.ending or "尚未达成"),
        ])

    # ------------------------------------------------------------------
    # JSON 快照
    # ------------------------------------------------------------------
    def to_snapshot(self):
        """生成 JSON 可序列化快照。

        注意：快照只保存永久状态、检查点、循环次数、事件指针与结局；
        当前循环的临时物品不属于档案，不进入快照。
        """
        return {
            "version": SAVE_VERSION,
            "seed": self.seed,
            "loop_count": self.loop_count,
            "event_pointer": self.event_pointer,
            "checkpoint": self.checkpoint,
            "unlocked_clues": sorted(self.unlocked_clues),
            "scored_clues": sorted(self.scored_clues),
            "score": self.score,
            "verified_timelines": sorted(self.verified_timelines),
            "upgrades": sorted(self.upgrades),
            "memories": dict(self.memories),
            "ending": self.ending,
            "finished": self.finished,
        }

    def load_snapshot(self, data):
        if data.get("version") != SAVE_VERSION:
            raise ValueError("不兼容的存档版本：{!r}".format(data.get("version")))
        game = Game(seed=data.get("seed", SEED))
        game.loop_count = data["loop_count"]
        game.event_pointer = data["event_pointer"]
        game.checkpoint = data["checkpoint"]
        game.unlocked_clues = set(data["unlocked_clues"])
        game.scored_clues = set(data["scored_clues"])
        game.score = data["score"]
        game.verified_timelines = set(data["verified_timelines"])
        # 仅恢复升级集合，不调用 _apply_upgrade，避免永久升级效果被重复应用。
        game.upgrades = set(data["upgrades"])
        game.memories = dict(data["memories"])
        # 临时物品从不写入快照，读档后当前循环从干净的临时状态开始。
        game.temp_items = []
        game.ending = data.get("ending")
        game.finished = data.get("finished", False)
        return game

    def save(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_snapshot(), handle,
                      ensure_ascii=False, indent=2, sort_keys=True)
        return "快照已保存：{}".format(path)

    def load(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        loaded = self.load_snapshot(data)
        self.__dict__.update(loaded.__dict__)
        return "快照已加载：{}".format(path)

    # ------------------------------------------------------------------
    # CMD 命令分发
    # ------------------------------------------------------------------
    def handle_command(self, line):
        parts = line.strip().split()
        if not parts:
            return ""
        command, args = parts[0].lower(), parts[1:]
        if command == "help":
            return MENU
        if command == "explore":
            return self.explore()
        if command == "talk":
            if not args:
                return "用法：talk <角色>"
            return self.talk(args[0], " ".join(args[1:]))
        if command == "checkpoint":
            return self.set_checkpoint()
        if command == "rewind":
            return self.rewind()
        if command == "verify":
            if not args:
                return "用法：verify <时间线>"
            return self.verify(args[0])
        if command == "save":
            if not args:
                return "用法：save <路径>"
            return self.save(args[0])
        if command == "load":
            if not args:
                return "用法：load <路径>"
            return self.load(args[0])
        if command == "status":
            return self.status()
        if command == "quit":
            return "已离开档案馆。"
        return "未知命令：{}（输入 help 查看菜单）".format(command)


def main():
    game = Game()
    print(MENU)
    while True:
        try:
            line = input("archive> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        output = game.handle_command(line)
        if output:
            print(output)
        if line.strip().lower() == "quit":
            break


if __name__ == "__main__":
    main()
