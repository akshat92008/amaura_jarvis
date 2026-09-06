"""
Snake Game in Python using Pygame
A complete, fully playable, and polished arcade Snake game.
"""

import sys
import os
import random
import math
from collections import deque, namedtuple
from enum import Enum
from typing import List, Optional, Set, Tuple

# Enable headless fallback if no display device is detected
if sys.platform != "darwin" and "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
except ImportError:
    pygame = None


# --- Core Data Structures & Enums ---

Point = namedtuple("Point", ["x", "y"])


class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    def is_opposite_to(self, other: "Direction") -> bool:
        if not isinstance(other, Direction):
            return False
        return (self.value[0] + other.value[0] == 0) and (self.value[1] + other.value[1] == 0)


class GameState(Enum):
    START = "START"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"


class FoodType(Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"


# --- Color Palette (Modern Dark Arcade) ---

COLOR_BG = (15, 17, 26)
COLOR_GRID = (25, 28, 42)
COLOR_BORDER = (45, 52, 75)
COLOR_HUD_BG = (22, 25, 38)
COLOR_HUD_LINE = (55, 65, 95)

COLOR_SNAKE_HEAD = (46, 204, 113)
COLOR_SNAKE_BODY = (39, 174, 96)
COLOR_SNAKE_EYE = (255, 255, 255)
COLOR_SNAKE_PUPIL = (20, 20, 20)

COLOR_FOOD = (235, 77, 75)
COLOR_FOOD_LEAF = (46, 204, 113)
COLOR_FOOD_STEM = (120, 70, 40)
COLOR_SPECIAL_FOOD = (241, 196, 15)
COLOR_SPECIAL_FOOD_GLOW = (243, 156, 18)

COLOR_TEXT_MAIN = (240, 240, 245)
COLOR_TEXT_MUTED = (160, 165, 185)
COLOR_TEXT_ACCENT = (46, 204, 113)
COLOR_TEXT_GOLD = (241, 196, 15)
COLOR_TEXT_RED = (235, 77, 75)


# --- Game Entities ---

class Food:
    def __init__(self, position: Point, food_type: FoodType = FoodType.REGULAR, lifetime: int = 0):
        self.position = position
        self.food_type = food_type
        self.points = 10 if food_type == FoodType.REGULAR else 30
        self.lifetime = lifetime
        self.max_lifetime = lifetime

    def is_expired(self) -> bool:
        return self.food_type == FoodType.SPECIAL and self.lifetime <= 0


class Snake:
    def __init__(self, start_pos: Point, length: int = 3, direction: Direction = Direction.RIGHT):
        self.initial_pos = start_pos
        self.initial_length = length
        self.initial_direction = direction
        self.body: List[Point] = []
        self.direction = direction
        self.grow_pending = 0
        self.reset()

    def reset(self):
        self.direction = self.initial_direction
        self.grow_pending = 0
        dx, dy = self.direction.value
        self.body = [
            Point(self.initial_pos.x - i * dx, self.initial_pos.y - i * dy)
            for i in range(self.initial_length)
        ]

    @property
    def head(self) -> Point:
        return self.body[0]

    def set_direction(self, new_direction: Direction) -> bool:
        if isinstance(new_direction, Direction) and not self.direction.is_opposite_to(new_direction):
            self.direction = new_direction
            return True
        return False

    def get_next_head_position(self, direction: Optional[Direction] = None) -> Point:
        d = direction if direction is not None else self.direction
        return Point(self.head.x + d.value[0], self.head.y + d.value[1])

    def step(self, new_head: Point):
        self.body.insert(0, new_head)
        if self.grow_pending > 0:
            self.grow_pending -= 1
        else:
            self.body.pop()

    def grow(self, amount: int = 1):
        self.grow_pending += amount

    def check_self_collision(self, candidate_head: Optional[Point] = None) -> bool:
        if candidate_head is not None:
            body_to_check = self.body if self.grow_pending > 0 else self.body[:-1]
            return candidate_head in body_to_check
        return self.head in self.body[1:]


# --- Game Logic Engine ---

class GameLogic:
    def __init__(
        self,
        grid_width: int = 40,
        grid_height: int = 28,
        cell_size: int = 20,
        high_score_file: Optional[str] = "highscore.txt",
    ):
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.cell_size = cell_size
        self.high_score_file = high_score_file

        start_x = grid_width // 2
        start_y = grid_height // 2
        self.snake = Snake(Point(start_x, start_y), length=3, direction=Direction.RIGHT)

        self.food: Optional[Food] = None
        self.special_food: Optional[Food] = None

        self.score = 0
        self.high_score = self.load_high_score()
        self.foods_eaten = 0
        self.state = GameState.START

        self.direction_queue: deque = deque(maxlen=2)

        self.spawn_food()

    @property
    def speed(self) -> int:
        """Dynamic speed: base 10, increases by 1 every 50 points, capped at 25."""
        return min(25, 10 + (self.score // 50))

    @property
    def is_game_over(self) -> bool:
        return self.state == GameState.GAME_OVER

    @property
    def is_paused(self) -> bool:
        return self.state == GameState.PAUSED

    @property
    def is_playing(self) -> bool:
        return self.state == GameState.PLAYING

    def start_game(self):
        if self.state == GameState.START:
            self.state = GameState.PLAYING

    def toggle_pause(self):
        if self.state == GameState.PLAYING:
            self.state = GameState.PAUSED
        elif self.state == GameState.PAUSED:
            self.state = GameState.PLAYING

    def reset_game(self):
        self.snake.reset()
        self.score = 0
        self.foods_eaten = 0
        self.special_food = None
        self.direction_queue.clear()
        self.spawn_food()
        self.state = GameState.PLAYING

    def queue_direction(self, new_dir: Direction):
        if self.state == GameState.START:
            self.start_game()
        if self.state != GameState.PLAYING:
            return
        last_dir = self.direction_queue[-1] if self.direction_queue else self.snake.direction
        if new_dir != last_dir and not last_dir.is_opposite_to(new_dir):
            self.direction_queue.append(new_dir)

    def is_out_of_bounds(self, pt: Point) -> bool:
        return pt.x < 0 or pt.x >= self.grid_width or pt.y < 0 or pt.y >= self.grid_height

    def get_empty_cells(self) -> List[Point]:
        occupied = set(self.snake.body)
        if self.food is not None:
            occupied.add(self.food.position)
        if self.special_food is not None:
            occupied.add(self.special_food.position)

        return [
            Point(x, y)
            for x in range(self.grid_width)
            for y in range(self.grid_height)
            if Point(x, y) not in occupied
        ]

    def spawn_food(self, position: Optional[Point] = None) -> Optional[Food]:
        if position is not None:
            self.food = Food(position, FoodType.REGULAR)
            return self.food

        occupied = set(self.snake.body)
        if self.special_food is not None:
            occupied.add(self.special_food.position)

        total_cells = self.grid_width * self.grid_height
        if len(occupied) >= total_cells:
            self.food = None
            return None

        if len(occupied) < total_cells * 0.75:
            for _ in range(100):
                x = random.randint(0, self.grid_width - 1)
                y = random.randint(0, self.grid_height - 1)
                p = Point(x, y)
                if p not in occupied:
                    self.food = Food(p, FoodType.REGULAR)
                    return self.food

        empty = [
            Point(x, y)
            for x in range(self.grid_width)
            for y in range(self.grid_height)
            if Point(x, y) not in occupied
        ]
        if empty:
            self.food = Food(random.choice(empty), FoodType.REGULAR)
        else:
            self.food = None
        return self.food

    def spawn_special_food(self, position: Optional[Point] = None, lifetime: int = 50) -> Optional[Food]:
        if position is not None:
            self.special_food = Food(position, FoodType.SPECIAL, lifetime=lifetime)
            return self.special_food

        occupied = set(self.snake.body)
        if self.food is not None:
            occupied.add(self.food.position)

        total_cells = self.grid_width * self.grid_height
        if len(occupied) >= total_cells:
            self.special_food = None
            return None

        for _ in range(100):
            x = random.randint(0, self.grid_width - 1)
            y = random.randint(0, self.grid_height - 1)
            p = Point(x, y)
            if p not in occupied:
                self.special_food = Food(p, FoodType.SPECIAL, lifetime=lifetime)
                return self.special_food

        empty = [
            Point(x, y)
            for x in range(self.grid_width)
            for y in range(self.grid_height)
            if Point(x, y) not in occupied
        ]
        if empty:
            self.special_food = Food(random.choice(empty), FoodType.SPECIAL, lifetime=lifetime)
        else:
            self.special_food = None
        return self.special_food

    def update(self) -> bool:
        if self.state != GameState.PLAYING:
            return False

        if self.direction_queue:
            next_dir = self.direction_queue.popleft()
            if not self.snake.direction.is_opposite_to(next_dir):
                self.snake.direction = next_dir

        next_head = self.snake.get_next_head_position()

        if self.is_out_of_bounds(next_head):
            self.handle_game_over()
            return False

        if self.snake.check_self_collision(next_head):
            self.handle_game_over()
            return False

        ate_regular = (self.food is not None and next_head == self.food.position)
        ate_special = (self.special_food is not None and next_head == self.special_food.position)

        if ate_regular:
            self.score += self.food.points
            self.foods_eaten += 1
            self.snake.grow(1)
            self.update_high_score()
            if self.foods_eaten % 5 == 0 and self.special_food is None:
                self.spawn_special_food()
            self.spawn_food()
        elif ate_special:
            self.score += self.special_food.points
            self.snake.grow(1)
            self.update_high_score()
            self.special_food = None

        self.snake.step(next_head)

        if self.special_food is not None and not ate_special:
            self.special_food.lifetime -= 1
            if self.special_food.lifetime <= 0:
                self.special_food = None

        return True

    def handle_game_over(self):
        self.state = GameState.GAME_OVER
        self.update_high_score()
        self.save_high_score()

    def update_high_score(self):
        if self.score > self.high_score:
            self.high_score = self.score

    def load_high_score(self) -> int:
        if not self.high_score_file:
            return 0
        try:
            if os.path.exists(self.high_score_file):
                with open(self.high_score_file, "r", encoding="utf-8") as f:
                    return int(f.read().strip())
        except (ValueError, OSError):
            pass
        return 0

    def save_high_score(self):
        if not self.high_score_file:
            return
        try:
            with open(self.high_score_file, "w", encoding="utf-8") as f:
                f.write(str(self.high_score))
        except OSError:
            pass


# --- Pygame Frontend ---

class SnakeGame:
    def __init__(
        self,
        grid_width: int = 40,
        grid_height: int = 28,
        cell_size: int = 20,
        hud_height: int = 40,
        headless: bool = False,
        high_score_file: Optional[str] = "highscore.txt",
    ):
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.cell_size = cell_size
        self.hud_height = hud_height
        self.width = grid_width * cell_size
        self.height = grid_height * cell_size + hud_height
        self.headless = headless

        self.logic = GameLogic(
            grid_width=grid_width,
            grid_height=grid_height,
            cell_size=cell_size,
            high_score_file=high_score_file,
        )

        self.running = False
        self.screen = None
        self.clock = None

        if pygame is not None:
            if self.headless:
                os.environ["SDL_VIDEODRIVER"] = "dummy"
                os.environ["SDL_AUDIODRIVER"] = "dummy"
            if not pygame.get_init():
                pygame.init()
            try:
                if not self.headless:
                    self.screen = pygame.display.set_mode((self.width, self.height))
                    pygame.display.set_caption("Snake Game")
                else:
                    self.screen = pygame.Surface((self.width, self.height))
            except pygame.error:
                self.screen = pygame.Surface((self.width, self.height))

            self.clock = pygame.time.Clock()

            try:
                if not pygame.font.get_init():
                    pygame.font.init()
                self.font_large = pygame.font.SysFont("Arial,Helvetica,sans-serif", 36, bold=True)
                self.font_medium = pygame.font.SysFont("Arial,Helvetica,sans-serif", 20, bold=True)
                self.font_small = pygame.font.SysFont("Arial,Helvetica,sans-serif", 14)
            except Exception:
                self.font_large = pygame.font.Font(None, 36)
                self.font_medium = pygame.font.Font(None, 20)
                self.font_small = pygame.font.Font(None, 14)

    def handle_event(self, event):
        if pygame is None:
            return
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_q:
                if self.logic.state in (GameState.START, GameState.GAME_OVER):
                    self.running = False
            elif event.key == pygame.K_p:
                self.logic.toggle_pause()
            elif event.key == pygame.K_r:
                self.logic.reset_game()
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                if self.logic.state == GameState.START:
                    self.logic.start_game()
                elif self.logic.state == GameState.GAME_OVER:
                    self.logic.reset_game()
                elif self.logic.state in (GameState.PLAYING, GameState.PAUSED):
                    self.logic.toggle_pause()
            elif event.key in (pygame.K_UP, pygame.K_w):
                self.logic.queue_direction(Direction.UP)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.logic.queue_direction(Direction.DOWN)
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self.logic.queue_direction(Direction.LEFT)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self.logic.queue_direction(Direction.RIGHT)

    def draw_hud(self):
        if self.screen is None:
            return
        hud_rect = pygame.Rect(0, 0, self.width, self.hud_height)
        pygame.draw.rect(self.screen, COLOR_HUD_BG, hud_rect)
        pygame.draw.line(
            self.screen,
            COLOR_HUD_LINE,
            (0, self.hud_height - 1),
            (self.width, self.hud_height - 1),
            2,
        )

        score_surf = self.font_medium.render(f"SCORE: {self.logic.score}", True, COLOR_TEXT_ACCENT)
        self.screen.blit(score_surf, (15, 10))

        best_surf = self.font_medium.render(f"BEST: {self.logic.high_score}", True, COLOR_TEXT_GOLD)
        best_rect = best_surf.get_rect(center=(self.width // 2, self.hud_height // 2))
        self.screen.blit(best_surf, best_rect)

        speed_text = f"SPEED: {self.logic.speed}"
        if self.logic.special_food is not None:
            remaining_s = (self.logic.special_food.lifetime // 10) + 1
            speed_text += f"  ★ BONUS: {remaining_s}s"
        speed_surf = self.font_small.render(speed_text, True, COLOR_TEXT_MUTED)
        speed_rect = speed_surf.get_rect(right=self.width - 15, centery=self.hud_height // 2)
        self.screen.blit(speed_surf, speed_rect)

    def draw_grid(self):
        if self.screen is None:
            return
        for x in range(0, self.width, self.cell_size):
            pygame.draw.line(
                self.screen,
                COLOR_GRID,
                (x, self.hud_height),
                (x, self.height),
                1,
            )
        for y in range(self.hud_height, self.height, self.cell_size):
            pygame.draw.line(
                self.screen,
                COLOR_GRID,
                (0, y),
                (self.width, y),
                1,
            )

        play_area = pygame.Rect(0, self.hud_height, self.width, self.height - self.hud_height)
        pygame.draw.rect(self.screen, COLOR_BORDER, play_area, 2)

    def draw_snake(self):
        if self.screen is None:
            return
        body = self.logic.snake.body
        body_len = len(body)
        for i, segment in enumerate(body):
            px = segment.x * self.cell_size
            py = self.hud_height + segment.y * self.cell_size
            rect = pygame.Rect(px + 1, py + 1, self.cell_size - 2, self.cell_size - 2)

            if i == 0:
                pygame.draw.rect(self.screen, COLOR_SNAKE_HEAD, rect, border_radius=6)

                eye_offset = 5
                pupil_offset = 6
                d = self.logic.snake.direction
                if d == Direction.RIGHT:
                    eye1 = (px + self.cell_size - eye_offset, py + 6)
                    eye2 = (px + self.cell_size - eye_offset, py + self.cell_size - 6)
                    p1 = (px + self.cell_size - pupil_offset + 2, py + 6)
                    p2 = (px + self.cell_size - pupil_offset + 2, py + self.cell_size - 6)
                elif d == Direction.LEFT:
                    eye1 = (px + eye_offset, py + 6)
                    eye2 = (px + eye_offset, py + self.cell_size - 6)
                    p1 = (px + pupil_offset - 2, py + 6)
                    p2 = (px + pupil_offset - 2, py + self.cell_size - 6)
                elif d == Direction.UP:
                    eye1 = (px + 6, py + eye_offset)
                    eye2 = (px + self.cell_size - 6, py + eye_offset)
                    p1 = (px + 6, py + pupil_offset - 2)
                    p2 = (px + self.cell_size - 6, py + pupil_offset - 2)
                else:  # DOWN
                    eye1 = (px + 6, py + self.cell_size - eye_offset)
                    eye2 = (px + self.cell_size - 6, py + self.cell_size - eye_offset)
                    p1 = (px + 6, py + self.cell_size - pupil_offset + 2)
                    p2 = (px + self.cell_size - 6, py + self.cell_size - pupil_offset + 2)

                pygame.draw.circle(self.screen, COLOR_SNAKE_EYE, eye1, 3)
                pygame.draw.circle(self.screen, COLOR_SNAKE_EYE, eye2, 3)
                pygame.draw.circle(self.screen, COLOR_SNAKE_PUPIL, p1, 1)
                pygame.draw.circle(self.screen, COLOR_SNAKE_PUPIL, p2, 1)
            else:
                factor = max(0.65, 1.0 - (i / max(1, body_len)) * 0.35)
                color = (
                    int(COLOR_SNAKE_BODY[0] * factor),
                    int(COLOR_SNAKE_BODY[1] * factor),
                    int(COLOR_SNAKE_BODY[2] * factor),
                )
                pygame.draw.rect(self.screen, color, rect, border_radius=4)

    def draw_food(self):
        if self.screen is None:
            return
        if self.logic.food is not None:
            fx = self.logic.food.position.x * self.cell_size
            fy = self.hud_height + self.logic.food.position.y * self.cell_size
            cx = fx + self.cell_size // 2
            cy = fy + self.cell_size // 2
            radius = self.cell_size // 2 - 2

            pygame.draw.circle(self.screen, COLOR_FOOD, (cx, cy), radius)
            pygame.draw.circle(self.screen, (255, 255, 255), (cx - 2, cy - 2), 2)
            pygame.draw.line(self.screen, COLOR_FOOD_STEM, (cx, cy - radius), (cx + 2, cy - radius - 3), 2)
            pygame.draw.circle(self.screen, COLOR_FOOD_LEAF, (cx + 3, cy - radius - 2), 2)

        if self.logic.special_food is not None:
            sx = self.logic.special_food.position.x * self.cell_size
            sy = self.hud_height + self.logic.special_food.position.y * self.cell_size
            cx = sx + self.cell_size // 2
            cy = sy + self.cell_size // 2
            radius = self.cell_size // 2 - 2

            pygame.draw.circle(self.screen, COLOR_SPECIAL_FOOD_GLOW, (cx, cy), radius + 2)
            pygame.draw.circle(self.screen, COLOR_SPECIAL_FOOD, (cx, cy), radius)
            pygame.draw.circle(self.screen, (255, 255, 255), (cx - 2, cy - 2), 2)

    def draw_start_screen(self):
        if self.screen is None:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((10, 12, 18, 220))
        self.screen.blit(overlay, (0, 0))

        title = self.font_large.render("SNAKE GAME", True, COLOR_TEXT_ACCENT)
        title_rect = title.get_rect(center=(self.width // 2, 160))
        self.screen.blit(title, title_rect)

        sub = self.font_small.render("Classic arcade snake built with Pygame", True, COLOR_TEXT_MUTED)
        sub_rect = sub.get_rect(center=(self.width // 2, 210))
        self.screen.blit(sub, sub_rect)

        ctrl1 = self.font_medium.render("Move: Arrow Keys or W / A / S / D", True, COLOR_TEXT_MAIN)
        ctrl1_rect = ctrl1.get_rect(center=(self.width // 2, 280))
        self.screen.blit(ctrl1, ctrl1_rect)

        ctrl2 = self.font_small.render("Pause: P or Space  |  Restart: R  |  Quit: ESC / Q", True, COLOR_TEXT_MUTED)
        ctrl2_rect = ctrl2.get_rect(center=(self.width // 2, 320))
        self.screen.blit(ctrl2, ctrl2_rect)

        prompt = self.font_medium.render("[ PRESS SPACE OR ENTER TO START ]", True, COLOR_TEXT_ACCENT)
        prompt_rect = prompt.get_rect(center=(self.width // 2, 400))
        self.screen.blit(prompt, prompt_rect)

    def draw_pause_screen(self):
        if self.screen is None:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((10, 12, 18, 190))
        self.screen.blit(overlay, (0, 0))

        title = self.font_large.render("PAUSED", True, COLOR_TEXT_MAIN)
        title_rect = title.get_rect(center=(self.width // 2, self.height // 2 - 40))
        self.screen.blit(title, title_rect)

        sub = self.font_medium.render("Press P or SPACE to resume", True, COLOR_TEXT_ACCENT)
        sub_rect = sub.get_rect(center=(self.width // 2, self.height // 2 + 15))
        self.screen.blit(sub, sub_rect)

        sub2 = self.font_small.render("Press R to restart", True, COLOR_TEXT_MUTED)
        sub2_rect = sub2.get_rect(center=(self.width // 2, self.height // 2 + 55))
        self.screen.blit(sub2, sub2_rect)

    def draw_game_over_screen(self):
        if self.screen is None:
            return
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((18, 10, 12, 220))
        self.screen.blit(overlay, (0, 0))

        title = self.font_large.render("GAME OVER", True, COLOR_TEXT_RED)
        title_rect = title.get_rect(center=(self.width // 2, 150))
        self.screen.blit(title, title_rect)

        if self.logic.score > 0 and self.logic.score == self.logic.high_score:
            high_badge = self.font_medium.render("★ NEW HIGH SCORE! ★", True, COLOR_TEXT_GOLD)
            high_badge_rect = high_badge.get_rect(center=(self.width // 2, 210))
            self.screen.blit(high_badge, high_badge_rect)

        score_txt = self.font_medium.render(f"Final Score: {self.logic.score}", True, COLOR_TEXT_MAIN)
        score_rect = score_txt.get_rect(center=(self.width // 2, 260))
        self.screen.blit(score_txt, score_rect)

        best_txt = self.font_small.render(f"Best Score: {self.logic.high_score}", True, COLOR_TEXT_GOLD)
        best_rect = best_txt.get_rect(center=(self.width // 2, 295))
        self.screen.blit(best_txt, best_rect)

        eaten_txt = self.font_small.render(f"Foods Eaten: {self.logic.foods_eaten}", True, COLOR_TEXT_MUTED)
        eaten_rect = eaten_txt.get_rect(center=(self.width // 2, 325))
        self.screen.blit(eaten_txt, eaten_rect)

        prompt = self.font_medium.render("Press [R] or [SPACE] to Play Again", True, COLOR_TEXT_ACCENT)
        prompt_rect = prompt.get_rect(center=(self.width // 2, 400))
        self.screen.blit(prompt, prompt_rect)

        quit_txt = self.font_small.render("Press [ESC] or [Q] to Quit", True, COLOR_TEXT_MUTED)
        quit_rect = quit_txt.get_rect(center=(self.width // 2, 440))
        self.screen.blit(quit_txt, quit_rect)

    def draw(self):
        if self.screen is None:
            return
        self.screen.fill(COLOR_BG)
        self.draw_grid()
        self.draw_food()
        self.draw_snake()
        self.draw_hud()

        if self.logic.state == GameState.START:
            self.draw_start_screen()
        elif self.logic.state == GameState.PAUSED:
            self.draw_pause_screen()
        elif self.logic.state == GameState.GAME_OVER:
            self.draw_game_over_screen()

    def run(self):
        if pygame is None:
            print("Error: pygame is not installed.", file=sys.stderr)
            return

        self.running = True
        time_since_last_tick = 0.0
        fps = 60

        while self.running:
            dt = self.clock.tick(fps) / 1000.0 if self.clock else 0.016
            time_since_last_tick += dt

            for event in pygame.event.get():
                self.handle_event(event)

            tick_interval = 1.0 / max(1, self.logic.speed)
            if self.logic.state == GameState.PLAYING:
                if time_since_last_tick >= tick_interval:
                    self.logic.update()
                    time_since_last_tick = 0.0
            else:
                time_since_last_tick = 0.0

            self.draw()
            if pygame.display.get_surface() is not None:
                pygame.display.flip()

        pygame.quit()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Snake Game in Pygame")
    parser.add_argument("--headless", action="store_true", help="Run without opening a display window")
    args = parser.parse_args()

    game = SnakeGame(headless=args.headless)
    game.run()


if __name__ == "__main__":
    main()
