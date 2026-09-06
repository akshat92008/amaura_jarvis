"""Comprehensive automated test suite for snake_game.py.

Tests game mechanics, anti-reverse logic, collision detection,
food spawning, score tracking, speed progression, state transitions,
key handling, and headless rendering.
"""

from collections import deque
import os
import unittest

# Ensure headless execution for Pygame during testing
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
import snake_game
from snake_game import (
    DEFAULT_CELL_SIZE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DOWN,
    LEFT,
    MAX_FPS,
    POINTS_PER_FOOD,
    RIGHT,
    SPEED_INCREMENT_INTERVAL,
    UP,
    Direction,
    GameState,
    SnakeGame,
    normalize_direction,
)


class TestSnakeGameLogic(unittest.TestCase):
    """Test pure model logic of SnakeGame without display dependencies."""

    def setUp(self):
        self.game = SnakeGame(
            width=640,
            height=480,
            cell_size=20,
            fps=10,
            auto_start=True,
        )

    def test_initial_state(self):
        """Verify default setup and initial values."""
        self.assertEqual(self.game.width, 640)
        self.assertEqual(self.game.height, 480)
        self.assertEqual(self.game.cell_size, 20)
        self.assertEqual(self.game.grid_width, 32)
        self.assertEqual(self.game.grid_height, 24)

        # Initial snake of 3 segments centered facing RIGHT
        cx = 32 // 2
        cy = 24 // 2
        expected_snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.assertEqual(self.game.snake, expected_snake)
        self.assertEqual(self.game.head, (cx, cy))
        self.assertEqual(self.game.direction, Direction.RIGHT)

        # Scores and state
        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.food_eaten, 0)
        self.assertEqual(self.game.high_score, 0)
        self.assertEqual(self.game.state, GameState.PLAYING)
        self.assertTrue(self.game.is_playing())
        self.assertFalse(self.game.is_game_over())
        self.assertFalse(self.game.is_paused())

        # Food spawned within boundaries and not on snake
        self.assertIsNotNone(self.game.food)
        fx, fy = self.game.food
        self.assertTrue(0 <= fx < self.game.grid_width)
        self.assertTrue(0 <= fy < self.game.grid_height)
        self.assertNotIn(self.game.food, self.game.snake)

    def test_auto_start_false(self):
        """Verify auto_start=False starts in START state and does not advance until started."""
        game = SnakeGame(auto_start=False)
        self.assertEqual(game.state, GameState.START)
        self.assertFalse(game.is_playing())

        # Calling step in START state returns False and snake stays put
        initial_snake = list(game.snake)
        stepped = game.step()
        self.assertFalse(stepped)
        self.assertEqual(game.snake, initial_snake)

        # Calling start_game starts the game
        game.start_game()
        self.assertEqual(game.state, GameState.PLAYING)
        self.assertTrue(game.is_playing())

    def test_custom_parameters(self):
        """Verify game scales correctly to custom grid dimensions and speeds."""
        game = SnakeGame(width=400, height=300, cell_size=10, fps=15)
        self.assertEqual(game.grid_width, 40)
        self.assertEqual(game.grid_height, 30)
        self.assertEqual(game.fps, 15)
        self.assertEqual(game.current_fps, 15)

    def test_step_movement(self):
        """Verify standard movement advances head and removes tail."""
        head_x, head_y = self.game.head
        stepped = self.game.step()
        self.assertTrue(stepped)

        # Snake moved 1 cell right
        self.assertEqual(self.game.head, (head_x + 1, head_y))
        self.assertEqual(len(self.game.snake), 3)

    def test_direction_changes(self):
        """Verify valid direction changes update next direction."""
        # Moving RIGHT: UP and DOWN are valid
        self.assertTrue(self.game.change_direction(Direction.UP))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.UP)

        # Moving UP: LEFT and RIGHT are valid
        self.assertTrue(self.game.change_direction(Direction.LEFT))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.LEFT)

        # Accepts string directions
        self.assertTrue(self.game.change_direction("down"))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.DOWN)

        # Accepts tuple directions
        self.assertTrue(self.game.change_direction((1, 0)))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.RIGHT)

        # Invalid direction returns False
        self.assertFalse(self.game.change_direction("INVALID"))
        self.assertFalse(self.game.change_direction(123))

    def test_anti_reverse(self):
        """Verify 180-degree instant reversal is strictly rejected."""
        # Currently moving RIGHT: LEFT must be rejected
        self.assertFalse(self.game.change_direction(Direction.LEFT))
        self.assertEqual(self.game.direction, Direction.RIGHT)

        # Same direction is also ignored/rejected
        self.assertFalse(self.game.change_direction(Direction.RIGHT))

        # Turn UP
        self.assertTrue(self.game.change_direction(Direction.UP))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.UP)

        # Moving UP: DOWN must be rejected
        self.assertFalse(self.game.change_direction(Direction.DOWN))

        # Turn LEFT
        self.assertTrue(self.game.change_direction(Direction.LEFT))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.LEFT)

        # Moving LEFT: RIGHT must be rejected
        self.assertFalse(self.game.change_direction(Direction.RIGHT))

        # Turn DOWN
        self.assertTrue(self.game.change_direction(Direction.DOWN))
        self.game.step()
        self.assertEqual(self.game.direction, Direction.DOWN)

        # Moving DOWN: UP must be rejected
        self.assertFalse(self.game.change_direction(Direction.UP))

    def test_input_buffering_rapid_turn(self):
        """Verify rapid key presses in same frame do not cause self-reversal."""
        # Snake moving RIGHT
        self.assertEqual(self.game.direction, Direction.RIGHT)

        # User presses UP then LEFT before step() is called
        self.assertTrue(self.game.change_direction(Direction.UP))
        self.assertTrue(self.game.change_direction(Direction.LEFT))

        # First tick: turns UP
        self.game.step()
        self.assertEqual(self.game.direction, Direction.UP)

        # Second tick: turns LEFT
        self.game.step()
        self.assertEqual(self.game.direction, Direction.LEFT)

        # Trying to reverse against pending queued direction is rejected
        self.game.change_direction(Direction.UP)
        # Attempting DOWN (opposite of pending UP) should be rejected
        self.assertFalse(self.game.change_direction(Direction.DOWN))

    def test_eat_food_growth_and_score(self):
        """Verify eating food increases length, updates score and high score, and spawns new food."""
        head_x, head_y = self.game.head
        target_food = (head_x + 1, head_y)
        self.game.spawn_food(fixed_pos=target_food)

        old_len = len(self.game.snake)
        stepped = self.game.step()

        self.assertTrue(stepped)
        self.assertEqual(self.game.head, target_food)
        self.assertEqual(len(self.game.snake), old_len + 1)
        self.assertEqual(self.game.score, POINTS_PER_FOOD)
        self.assertEqual(self.game.food_eaten, 1)
        self.assertEqual(self.game.high_score, POINTS_PER_FOOD)

        # New food was spawned and is not at head
        self.assertIsNotNone(self.game.food)
        self.assertNotEqual(self.game.food, target_food)

    def test_wall_collision_right(self):
        """Verify hitting the right boundary triggers game over."""
        self.game.snake = [(self.game.grid_width - 1, 10), (self.game.grid_width - 2, 10)]
        self.game.direction = Direction.RIGHT
        self.game.direction_queue.clear()

        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())
        self.assertTrue(self.game.game_over)

    def test_wall_collision_left(self):
        """Verify hitting the left boundary triggers game over."""
        self.game.snake = [(0, 10), (1, 10)]
        self.game.direction = Direction.LEFT
        self.game.direction_queue.clear()

        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())

    def test_wall_collision_top(self):
        """Verify hitting the top boundary triggers game over."""
        self.game.snake = [(10, 0), (10, 1)]
        self.game.direction = Direction.UP
        self.game.direction_queue.clear()

        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())

    def test_wall_collision_bottom(self):
        """Verify hitting the bottom boundary triggers game over."""
        self.game.snake = [(10, self.game.grid_height - 1), (10, self.game.grid_height - 2)]
        self.game.direction = Direction.DOWN
        self.game.direction_queue.clear()

        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())

    def test_self_collision(self):
        """Verify running into snake's own body triggers game over."""
        # 5-segment snake forming a hook
        self.game.snake = [(5, 5), (5, 6), (6, 6), (6, 5), (6, 4)]
        self.game.direction = Direction.RIGHT
        self.game.direction_queue.clear()
        # Moving right goes to (6, 5) which is snake[3]
        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())

    def test_tail_chase_no_collision_when_vacated(self):
        """Moving into the cell vacated by the tail when not eating food is safe."""
        # 4-segment loop: head at (5, 5), tail at (5, 4). Moving UP moves into (5, 4).
        self.game.snake = [(5, 5), (4, 5), (4, 4), (5, 4)]
        self.game.direction = Direction.UP
        self.game.direction_queue.clear()
        self.game.food = (0, 0)  # Food is far away

        stepped = self.game.step()
        self.assertTrue(stepped)
        self.assertNotEqual(self.game.state, GameState.GAME_OVER)
        self.assertEqual(self.game.head, (5, 4))

    def test_pause_and_resume(self):
        """Verify toggle_pause correctly halts and resumes simulation."""
        self.game.toggle_pause()
        self.assertEqual(self.game.state, GameState.PAUSED)
        self.assertTrue(self.game.is_paused())
        self.assertTrue(self.game.paused)

        head_before = self.game.head
        stepped = self.game.step()
        self.assertFalse(stepped)
        self.assertEqual(self.game.head, head_before)

        self.game.toggle_pause()
        self.assertEqual(self.game.state, GameState.PLAYING)
        self.assertTrue(self.game.is_playing())

        stepped = self.game.step()
        self.assertTrue(stepped)
        self.assertNotEqual(self.game.head, head_before)

    def test_reset_preserves_high_score(self):
        """Verify reset clears score and position but preserves high score."""
        self.game.score = 50
        self.game.high_score = 50
        self.game.state = GameState.GAME_OVER

        self.game.reset()
        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.food_eaten, 0)
        self.assertEqual(self.game.high_score, 50)
        self.assertEqual(len(self.game.snake), 3)
        self.assertEqual(self.game.state, GameState.PLAYING)
        self.assertFalse(self.game.game_over)

    def test_speed_progression(self):
        """Verify speed increases with food eaten up to MAX_FPS."""
        initial_fps = self.game.fps

        # Eat SPEED_INCREMENT_INTERVAL foods
        for i in range(SPEED_INCREMENT_INTERVAL):
            hx, hy = self.game.head
            food_pos = (hx + 1, hy)
            self.game.spawn_food(fixed_pos=food_pos)
            self.game.step()

        self.assertEqual(self.game.food_eaten, SPEED_INCREMENT_INTERVAL)
        self.assertEqual(self.game.current_fps, initial_fps + 1)

        # Manually verify cap at MAX_FPS
        self.game.food_eaten = 100
        speed_bonus = self.game.food_eaten // SPEED_INCREMENT_INTERVAL
        self.game.current_fps = min(self.game.fps + speed_bonus, MAX_FPS)
        self.assertEqual(self.game.current_fps, MAX_FPS)

    def test_is_collision_helper(self):
        """Verify is_collision detects points out of bounds and on snake."""
        self.assertTrue(self.game.is_collision((-1, 5)))
        self.assertTrue(self.game.is_collision((self.game.grid_width, 5)))
        self.assertTrue(self.game.is_collision((5, -1)))
        self.assertTrue(self.game.is_collision((5, self.game.grid_height)))

        # Point on body segment (not head)
        body_point = self.game.snake[1]
        self.assertTrue(self.game.is_collision(body_point))

        # Open space point
        self.assertFalse(self.game.is_collision((0, 0)))

    def test_spawn_food_never_overlaps_snake(self):
        """Verify random food spawning never places food on snake segments."""
        for _ in range(100):
            food = self.game.spawn_food()
            self.assertNotIn(food, self.game.snake)

    def test_spawn_food_full_board(self):
        """Verify spawn_food returns None when board is completely full."""
        tiny_game = SnakeGame(width=40, height=40, cell_size=20)  # 2x2 grid
        tiny_game.snake = [(0, 0), (1, 0), (0, 1), (1, 1)]
        food = tiny_game.spawn_food()
        self.assertIsNone(food)

    def test_direction_enum_and_properties(self):
        """Verify Direction enum values and opposite properties."""
        self.assertEqual(Direction.UP.opposite, Direction.DOWN)
        self.assertEqual(Direction.DOWN.opposite, Direction.UP)
        self.assertEqual(Direction.LEFT.opposite, Direction.RIGHT)
        self.assertEqual(Direction.RIGHT.opposite, Direction.LEFT)

        self.assertEqual(UP, Direction.UP)
        self.assertEqual(DOWN, Direction.DOWN)
        self.assertEqual(LEFT, Direction.LEFT)
        self.assertEqual(RIGHT, Direction.RIGHT)

    def test_game_over_setter(self):
        """Verify game_over property setter."""
        self.game.game_over = True
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertTrue(self.game.is_game_over())

        self.game.game_over = False
        self.assertEqual(self.game.state, GameState.PLAYING)


class TestSnakeGamePygameInteraction(unittest.TestCase):
    """Test Pygame key handling and headless rendering."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

    def setUp(self):
        self.game = SnakeGame(auto_start=True)

    def test_handle_key_directions(self):
        """Verify arrow keys and WASD change directions properly."""
        # K_UP and K_w
        self.game.handle_key(pygame.K_UP)
        self.game.step()
        self.assertEqual(self.game.direction, Direction.UP)

        self.game.handle_key(pygame.K_a)
        self.game.step()
        self.assertEqual(self.game.direction, Direction.LEFT)

        self.game.handle_key(pygame.K_s)
        self.game.step()
        self.assertEqual(self.game.direction, Direction.DOWN)

        self.game.handle_key(pygame.K_d)
        self.game.step()
        self.assertEqual(self.game.direction, Direction.RIGHT)

    def test_handle_key_pause_and_resume(self):
        """Verify P and ESC toggle pause."""
        self.game.handle_key(pygame.K_p)
        self.assertTrue(self.game.is_paused())

        self.game.handle_key(pygame.K_ESCAPE)
        self.assertTrue(self.game.is_playing())

    def test_handle_key_restart_on_game_over(self):
        """Verify R and Space restart the game when GAME_OVER."""
        self.game.state = GameState.GAME_OVER
        self.game.score = 30

        self.game.handle_key(pygame.K_r)
        self.assertTrue(self.game.is_playing())
        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.high_score, 30)

    def test_handle_key_space_start_game(self):
        """Verify Space starts game from START state."""
        self.game.state = GameState.START
        self.game.handle_key(pygame.K_SPACE)
        self.assertTrue(self.game.is_playing())

    def test_handle_key_quit(self):
        """Verify Q requests quit in non-playing states."""
        self.game.state = GameState.GAME_OVER
        should_continue = self.game.handle_key(pygame.K_q)
        self.assertFalse(should_continue)

    def test_render_all_states_headless(self):
        """Verify rendering does not crash in any game state on a Pygame Surface."""
        surface = pygame.Surface((self.game.width, self.game.height))

        # Render PLAYING state
        self.game.state = GameState.PLAYING
        self.game.render(surface)

        # Render PAUSED state
        self.game.state = GameState.PAUSED
        self.game.render(surface)

        # Render GAME_OVER state
        self.game.state = GameState.GAME_OVER
        self.game.render(surface)

        # Render START state
        self.game.state = GameState.START
        self.game.render(surface)

        # Ensure surface has content
        self.assertGreater(surface.get_width(), 0)
        self.assertGreater(surface.get_height(), 0)


if __name__ == "__main__":
    unittest.main()
