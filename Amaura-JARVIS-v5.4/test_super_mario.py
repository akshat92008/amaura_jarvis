"""
test_super_mario.py - Automated test suite for SuperMario.py

Verifies:
- Jumping physics, gravity, horizontal acceleration, friction, and variable jump height
- Platform collisions: landing, ceiling bumps, question blocks, bricks, and walls
- Coin collection and score increment
- Enemy (Goomba) patrolling, wall bouncing, stomping mechanics, and damage
- Death boundary handling (falling below screen/into pit)
- Score, coin, and life tracking
- Camera tracking and game state transitions (PLAYING, GAME_OVER, VICTORY)
"""

import os
import unittest
from collections import defaultdict
import pygame

# Ensure headless environment before pygame operations
os.environ["SDL_VIDEODRIVER"] = "dummy"

from SuperMario import (
    Player, Platform, Brick, QuestionBlock, Pipe, Coin, Enemy, Flagpole, Castle,
    Camera, Level, Game,
    GRAVITY, MAX_FALL_SPEED, JUMP_FORCE, BOUNCE_FORCE, DEATH_Y
)


class TestSuperMario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not pygame.get_init():
            pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()

    def setUp(self):
        self.player = Player(100, 400)

    def test_player_initial_state(self):
        """Player should initialize with correct physics and game stats."""
        self.assertEqual(self.player.rect.x, 100)
        self.assertEqual(self.player.rect.y, 400)
        self.assertEqual(self.player.lives, 3)
        self.assertEqual(self.player.score, 0)
        self.assertEqual(self.player.coins, 0)
        self.assertTrue(self.player.is_alive)
        self.assertFalse(self.player.on_ground)

    def test_gravity_in_air(self):
        """Player in air should accelerate downwards under gravity until max speed."""
        initial_vy = self.player.vel_y
        self.player.update([])
        self.assertAlmostEqual(self.player.vel_y, initial_vy + GRAVITY, places=3)
        self.assertFalse(self.player.on_ground)

        # Let player fall for many frames to test terminal velocity
        self.player.rect.y = -5000
        for _ in range(50):
            self.player.update([])
        self.assertEqual(self.player.vel_y, MAX_FALL_SPEED)

    def test_jump_physics(self):
        """Player can only jump when on ground; jump applies upward velocity."""
        # In air: jump should not trigger
        self.player.on_ground = False
        self.player.jump()
        self.assertEqual(self.player.vel_y, 0.0)

        # On ground: jump should trigger
        self.player.on_ground = True
        self.player.jump()
        self.assertEqual(self.player.vel_y, JUMP_FORCE)
        self.assertFalse(self.player.on_ground)

    def test_cut_jump_variable_height(self):
        """Releasing jump key early cuts upward velocity."""
        self.player.on_ground = True
        self.player.jump()
        self.assertEqual(self.player.vel_y, JUMP_FORCE)
        self.player.cut_jump()
        self.assertAlmostEqual(self.player.vel_y, JUMP_FORCE * 0.5, places=3)

    def test_player_handle_input_movement(self):
        """Player responds to keyboard inputs for walking and deceleration."""
        # Press Right
        keys = defaultdict(int)
        keys[pygame.K_RIGHT] = 1
        self.player.handle_input(keys)
        self.assertGreater(self.player.vel_x, 0)
        self.assertTrue(self.player.facing_right)

        # Press Left
        keys = defaultdict(int)
        keys[pygame.K_LEFT] = 1
        self.player.vel_x = 0.0
        self.player.handle_input(keys)
        self.assertLess(self.player.vel_x, 0)
        self.assertFalse(self.player.facing_right)

        # Friction when no keys pressed
        keys = defaultdict(int)
        self.player.vel_x = 2.0
        self.player.handle_input(keys)
        self.assertLess(self.player.vel_x, 2.0)

    def test_platform_landing_collision(self):
        """Player falling onto a platform should land cleanly on top and reset vel_y."""
        platform = Platform(50, 430, 200, 50)
        self.player.rect.x = 100
        self.player.rect.y = 400
        self.player.vel_y = 5.0
        self.player.on_ground = False

        self.player.update([platform])
        self.assertEqual(self.player.rect.bottom, platform.rect.top)
        self.assertEqual(self.player.vel_y, 0.0)
        self.assertTrue(self.player.on_ground)

    def test_platform_ceiling_collision(self):
        """Player jumping up into a platform ceiling stops rising."""
        platform = Platform(50, 300, 200, 20)
        self.player.rect.x = 100
        self.player.rect.y = 310
        self.player.vel_y = -8.0
        self.player.on_ground = False

        self.player.update([platform])
        self.assertEqual(self.player.rect.top, platform.rect.bottom)
        self.assertEqual(self.player.vel_y, 0.0)

    def test_platform_horizontal_wall_collision(self):
        """Player cannot walk through solid vertical walls/pipes."""
        pipe = Pipe(150, 350, 48, 80)
        self.player.rect.x = 115
        self.player.rect.y = 360
        self.player.vel_x = 10.0

        self.player.update([pipe])
        self.assertEqual(self.player.rect.right, pipe.rect.left)
        self.assertEqual(self.player.vel_x, 0.0)

    def test_walk_off_platform_falls(self):
        """Walking off a platform detects absence of ground support and applies gravity."""
        platform = Platform(0, 450, 100, 50)
        self.player.rect.x = 50
        self.player.rect.bottom = platform.rect.top
        self.player.on_ground = True

        # While on platform, on_ground stays True
        self.player.update([platform])
        self.assertTrue(self.player.on_ground)
        self.assertEqual(self.player.vel_y, 0.0)

        # Move player past platform edge (x=110)
        self.player.rect.x = 110
        self.player.update([platform])
        self.assertFalse(self.player.on_ground)
        self.assertGreater(self.player.vel_y, 0.0)

    def test_question_block_gives_coin_and_score(self):
        """Hitting a question block from below dispenses coin and awards score."""
        qblock = QuestionBlock(100, 300, has_coin=True)
        self.assertFalse(qblock.is_hit)

        # Hit block
        qblock.hit(self.player)
        self.assertTrue(qblock.is_hit)
        self.assertEqual(self.player.coins, 1)
        self.assertEqual(self.player.score, 200)

        # Second hit should not give another coin
        qblock.hit(self.player)
        self.assertEqual(self.player.coins, 1)
        self.assertEqual(self.player.score, 200)

    def test_brick_bump(self):
        """Hitting a brick block triggers bump animation without crashing."""
        brick = Brick(100, 300)
        brick.hit(self.player)
        self.assertEqual(brick.bump_offset, -6)
        brick.update()
        self.assertEqual(brick.bump_offset, -5)

    def test_coin_collection(self):
        """Overlapping coin increases player score and coins count and removes coin."""
        coin_group = pygame.sprite.Group()
        coin = Coin(100, 400)
        coin_group.add(coin)

        self.assertTrue(coin.alive())
        coin.collect(self.player)
        self.assertFalse(coin.alive())
        self.assertEqual(self.player.coins, 1)
        self.assertEqual(self.player.score, 200)

    def test_enemy_patrol_and_reverse(self):
        """Enemy moves horizontally and reverses at patrol edge or wall."""
        enemy = Enemy(200, 400, patrol_range=20)
        initial_dir = enemy.vel_x
        self.assertLess(initial_dir, 0)

        # Force enemy to left boundary
        enemy.rect.left = enemy.patrol_left - 5
        enemy.update([])
        self.assertGreater(enemy.vel_x, 0)

        # Force enemy to right boundary
        enemy.rect.right = enemy.patrol_right + 5
        enemy.update([])
        self.assertLess(enemy.vel_x, 0)

    def test_enemy_stomp_mechanic(self):
        """Stomping on enemy from above defeats enemy, bounces player, and adds score."""
        game = Game(headless=True)
        player = game.player
        enemy = Enemy(100, 468)
        game.level.enemies.empty()
        game.level.enemies.add(enemy)

        # Position player falling right above enemy
        player.rect.x = 100
        player.rect.bottom = enemy.rect.top + 2
        player.vel_y = 4.0  # falling down
        player.on_ground = False

        game.update()
        self.assertTrue(enemy.squished)
        self.assertFalse(enemy.is_alive)
        self.assertEqual(player.vel_y, BOUNCE_FORCE)
        self.assertEqual(player.score, 100)

    def test_enemy_damages_player_from_side(self):
        """Touching enemy from the side damages player and reduces lives."""
        game = Game(headless=True)
        player = game.player
        player.invulnerable_timer = 0
        enemy = Enemy(110, 468)
        game.level.enemies.empty()
        game.level.enemies.add(enemy)

        # Mario walking into enemy sideways at ground level
        player.rect.x = 90
        player.rect.y = 460
        player.vel_y = 0.0
        player.on_ground = True

        initial_lives = player.lives
        game.update()
        self.assertFalse(player.is_alive)
        self.assertEqual(player.lives, initial_lives - 1)

    def test_death_boundary_pit(self):
        """Falling below DEATH_Y triggers death and life loss."""
        self.player.rect.y = DEATH_Y + 10
        self.player.update([])
        self.assertFalse(self.player.is_alive)
        self.assertEqual(self.player.lives, 2)

    def test_flagpole_victory(self):
        """Touching the flagpole triggers stage victory."""
        game = Game(headless=True)
        flagpole = game.level.flagpole
        game.player.rect.x = flagpole.rect.x
        game.player.rect.y = flagpole.rect.y + 50

        game.update()
        self.assertTrue(flagpole.reached)
        self.assertEqual(game.state, Game.STATE_VICTORY)
        self.assertGreaterEqual(game.player.score, 1000)

    def test_game_over_state_when_lives_exhausted(self):
        """When player has no lives left and dies, state becomes GAME_OVER."""
        game = Game(headless=True)
        game.player.lives = 0
        game.player.is_alive = False
        game.player.dead_timer = 0

        game.update()
        self.assertEqual(game.state, Game.STATE_GAME_OVER)

    def test_game_reset(self):
        """Resetting the game restores full health, lives, and level elements."""
        game = Game(headless=True)
        game.player.lives = 1
        game.player.score = 5000
        game.reset_game()

        self.assertEqual(game.player.lives, 3)
        self.assertEqual(game.player.score, 0)
        self.assertEqual(game.state, Game.STATE_PLAYING)
        self.assertTrue(len(game.level.enemies) > 0)
        self.assertTrue(len(game.level.coins) > 0)

    def test_camera_tracking(self):
        """Camera smoothly scrolls right with player and clamps at boundary."""
        camera = Camera(3000, 600)
        target = pygame.Rect(1200, 400, 30, 40)
        camera.update(target)
        self.assertGreater(camera.x, 0)
        # Apply offset check
        screen_rect = camera.apply(target)
        self.assertEqual(screen_rect.x, target.x - camera.x)

    def test_level_elements(self):
        """Level initializes with proper platform count, coins, enemies, flagpole, and castle."""
        level = Level()
        self.assertGreater(len(level.platforms), 5)
        self.assertGreater(len(level.coins), 5)
        self.assertGreater(len(level.enemies), 3)
        self.assertIsNotNone(level.flagpole)
        self.assertIsNotNone(level.castle)
        self.assertGreater(level.width, 3000)

    def test_headless_render(self):
        """Rendering in headless mode should execute without exceptions."""
        game = Game(headless=True)
        game.draw()
        game.state = Game.STATE_MENU
        game.draw()
        game.state = Game.STATE_GAME_OVER
        game.draw()
        game.state = Game.STATE_VICTORY
        game.draw()


if __name__ == '__main__':
    unittest.main()
