#!/usr/bin/env python3
"""Ludo 飞行棋:2~4 人对战,纯标准库.

规则(标准简化版):
- 52 格主赛道,每人 4 枚棋子,从大本营出发.
- 掷出 6 点才能出营;出营落到起点格.
- 落到对手棋子所在格(非安全格)则吃掉对方,送回大本营.
- 安全格:4 个起点格 + 4 个星形格,共 8 格,不可被吃.
- 走完主赛道进入 5 格终点道,需精确点数到达终点.
- 掷出 6 / 吃子 / 棋子到家均可再掷一次;连续三次 6 则本轮作废.
- 4 枚棋子全部到家者获胜.
"""

import argparse
import copy
import random
import sys

TRACK = 52
SAFE = frozenset({0, 8, 13, 21, 26, 34, 39, 47})
HOME_COL = 5          # 终点道格数
FINISH = 51 + HOME_COL  # 56 = 到家
BASE = -1
MAX_ROLLS = 2000      # 单局掷骰上限,防无限对局
NAMES = ["红", "绿", "黄", "蓝"]


class IllegalMove(Exception):
    pass


class Ludo:
    def __init__(self, n_players=2, seed=None):
        if n_players not in (2, 4):
            raise ValueError("只支持 2 或 4 名玩家")
        self.n = n_players
        self.rng = random.Random(seed)
        # 相对进度: -1=大本营, 0~50=主赛道, 51~55=终点道, 56=到家
        self.tokens = [[BASE] * 4 for _ in range(n_players)]
        self.turn = 0
        self.sixes = 0          # 连续 6 的次数
        self.winner = None
        self.rolls = 0

    @property
    def starts(self):
        return [0, 26] if self.n == 2 else [0, 13, 26, 39]

    def abs_pos(self, player, p):
        """相对进度 -> 主赛道绝对格(终点道/大本营返回 None)."""
        if 0 <= p <= 50:
            return (self.starts[player] + p) % TRACK
        return None

    def legal_moves(self, player, roll):
        """返回可走的棋子下标列表."""
        if self.winner is not None:
            return []
        if self.sixes >= 3:
            return []  # 连续三次 6,本轮作废
        moves = []
        for i, p in enumerate(self.tokens[player]):
            if p == BASE:
                if roll == 6:
                    moves.append(i)
            elif p < FINISH:
                if p + roll <= FINISH:
                    moves.append(i)
        return moves

    def _capture_at(self, player, square):
        """在绝对格 square 上吃掉对手棋子(安全格除外),返回被吃数量."""
        if square in SAFE:
            return 0
        n = 0
        for op in range(self.n):
            if op == player:
                continue
            for j, q in enumerate(self.tokens[op]):
                if self.abs_pos(op, q) == square:
                    self.tokens[op][j] = BASE
                    n += 1
        return n

    def apply(self, player, idx, roll):
        """执行走子,返回事件 dict.非法走法抛 IllegalMove."""
        if idx not in self.legal_moves(player, roll):
            raise IllegalMove(f"非法走法: 玩家{player} 棋子{idx} 掷{roll}")
        p = self.tokens[player][idx]
        captured = 0
        homed = False
        if p == BASE:
            new_p = 0
        else:
            new_p = p + roll
        self.tokens[player][idx] = new_p
        sq = self.abs_pos(player, new_p)
        if sq is not None:
            captured = self._capture_at(player, sq)
        if new_p == FINISH:
            homed = True
        if all(t == FINISH for t in self.tokens[player]):
            self.winner = player
        # 奖励回合:掷 6 / 吃子 / 到家(且未终局)
        extra = (roll == 6 or captured > 0 or homed) and self.winner is None
        return {"captured": captured, "homed": homed, "extra": extra}

    def roll_dice(self):
        return self.rng.randint(1, 6)

    def step(self, player, roll, idx=None):
        """走一步:返回 (events, next_player).idx 为 None 时用 AI 选子."""
        if idx is None:
            idx = ai_choose(self, player, roll)
        events = self.apply(player, idx, roll)
        self.rolls += 1
        if roll == 6:
            self.sixes += 1
        else:
            self.sixes = 0
        if self.sixes >= 3:
            # 连续三次 6:本轮作废,直接换手
            self.sixes = 0
            return events, (player + 1) % self.n
        if events["extra"]:
            return events, player
        return events, (player + 1) % self.n

    def play_game(self, verbose=False):
        """AI 对 AI 完整一局,返回 winner(或 None 表和棋)."""
        while self.winner is None and self.rolls < MAX_ROLLS:
            roll = self.roll_dice()
            moves = self.legal_moves(self.turn, roll)
            if verbose:
                print(f"{NAMES[self.turn]} 掷 {roll}: 可走 {moves}")
            if moves:
                events, nxt = self.step(self.turn, roll)
                if verbose:
                    print(f"  -> 吃子{events['captured']} 到家{events['homed']} "
                          f"{'再掷' if events['extra'] else ''}")
            else:
                nxt = (self.turn + 1) % self.n
                self.sixes = 0
                self.rolls += 1
            self.turn = nxt
        return self.winner


def danger_after(game, player, new_p):
    """走完后落在主赛道非安全格、且 1~6 格后有对手棋子 -> 危险."""
    sq = game.abs_pos(player, new_p)
    if sq is None or sq in SAFE:
        return False
    for op in range(game.n):
        if op == player:
            continue
        for q in game.tokens[op]:
            oq = game.abs_pos(op, q)
            if oq is None:
                continue
            if 1 <= (sq - oq) % TRACK <= 6:
                return True
    return False


def ai_choose(game, player, roll):
    """贪心 AI:吃子 > 到家 > 出营 > 进度 > 避险."""
    moves = game.legal_moves(player, roll)
    if not moves:
        raise IllegalMove("AI 无棋可走")
    best, best_score = moves[0], None
    for i in moves:
        p = game.tokens[player][i]
        new_p = 0 if p == BASE else p + roll
        # 模拟吃子数
        sim = copy.deepcopy(game)
        try:
            ev = sim.apply(player, i, roll)
        except IllegalMove:
            continue
        score = ev["captured"] * 100 + (80 if ev["homed"] else 0)
        if p == BASE:
            score += 50
        score += new_p * 0.5
        if danger_after(game, player, new_p):
            score -= 30
        # 离开危险格奖励
        if p != BASE and danger_after(game, player, p) and not danger_after(game, player, new_p):
            score += 10
        score += game.rng.random()  # 平局随机
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def render(game):
    lines = []
    for pl in range(game.n):
        ts = []
        for p in game.tokens[pl]:
            if p == BASE:
                ts.append("营")
            elif p == FINISH:
                ts.append("家")
            elif p > 50:
                ts.append(f"终{p - 50}")
            else:
                ts.append(str(game.abs_pos(pl, p)))
        lines.append(f"{NAMES[pl]}: {' '.join(ts)}")
    return "\n".join(lines)


def play_interactive(n_players):
    game = Ludo(n_players)
    print(f"Ludo 飞行棋,{n_players} 人对战,输入回车掷骰.")
    while game.winner is None and game.rolls < MAX_ROLLS:
        pl = game.turn
        print("----")
        print(render(game))
        input(f"{NAMES[pl]} 回车掷骰...")
        roll = game.roll_dice()
        print(f"掷出 {roll}")
        moves = game.legal_moves(pl, roll)
        if not moves:
            print("无棋可走.")
            game.turn = (pl + 1) % game.n
            game.rolls += 1
            continue
        print("可走棋子:", moves)
        sug = ai_choose(game, pl, roll)
        raw = input(f"选棋子下标(回车用 AI 推荐 {sug}): ").strip()
        idx = sug if raw == "" else int(raw)
        try:
            events, nxt = game.step(pl, roll, idx)
        except (IllegalMove, ValueError) as e:
            print("非法:", e)
            continue
        if events["captured"]:
            print(f"吃掉 {events['captured']} 子!")
        if events["homed"]:
            print("一子到家!")
        game.turn = nxt
    if game.winner is not None:
        print(f"{NAMES[game.winner]} 获胜!")
    else:
        print("和棋(步数上限).")


def play_auto(n_players, games, seed, verbose):
    rng = random.Random(seed)
    wins = [0] * n_players
    draws = 0
    for g in range(games):
        game = Ludo(n_players, seed=rng.randint(0, 2 ** 31 - 1))
        w = game.play_game(verbose=verbose)
        if w is None:
            draws += 1
            print(f"第 {g + 1}/{games} 局:和棋")
        else:
            wins[w] += 1
            print(f"第 {g + 1}/{games} 局:{NAMES[w]}胜 ({game.rolls} 掷)")
    summary = " ".join(f"{NAMES[i]}胜{wins[i]}" for i in range(n_players))
    print(f"总计:{summary} 和棋{draws}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ludo 飞行棋")
    ap.add_argument("--players", type=int, default=2, choices=[2, 4])
    ap.add_argument("--auto", action="store_true", help="AI 对 AI 自动演示")
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.auto:
        play_auto(args.players, args.games, args.seed, args.verbose)
    else:
        if not sys.stdin.isatty():
            print("交互模式需要终端;无头演示请用 --auto", file=sys.stderr)
            sys.exit(2)
        play_interactive(args.players)


if __name__ == "__main__":
    main()
