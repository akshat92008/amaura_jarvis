"""
Unit Tests for Asteroids Arcade Game
====================================
Comprehensive tests verifying:
- Ship rotation
- Inertia thrust physics
- Screen wrapping
- Splitting rock asteroids
- Laser projectile shooting
- Score tracking
- Collision detection and game state progression
"""

import math
import os
import unittest

# Ensure headless execution for testing environments
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

from asteroids import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    ASTEROID_LARGE,
    ASTEROID_MEDIUM,
    ASTEROID_SMALL,
    ASTEROID_RADII,
    ASTEROID_SCORES,
    wrap_position,
    Laser,
    Bullet,
    Asteroid,
    Ship,
    AsteroidsGame,
    Game,
)


class TestShipRotation(unittest.TestCase):
    """Verify ship orientation, rotation controls, and heading vectors."""
    def setUp(self):
        self.ship = Ship(x=400, y=300, angle=0.0)

    def test_initial_angle(self):
        self.assertEqual(self.ship.angle, 0.0)
        hx, hy = self.ship.heading
        self.assertAlmostEqual(hx, 0.0, places=5)
        self.assertAlmostEqual(hy, -1.0, places=5)

    def test_rotate_right(self):
        # Default rotation_speed is 5.0 degrees
        self.ship.rotate_right()
        self.assertEqual(self.ship.angle, 5.0)
        self.ship.rotate_right(3.0)
        self.assertEqual(self.ship.angle, 20.0)

    def test_rotate_left(self):
        self.ship.rotate_left()
        self.assertEqual(self.ship.angle, 355.0)
        self.ship.rotate_left(2.0)
        self.assertEqual(self.ship.angle, 345.0)

    def test_full_circle_rotation(self):
        # 72 steps of 5 degrees = 360 degrees = 0.0
        for _ in range(72):
            self.ship.rotate_right()
        self.assertAlmostEqual(self.ship.angle, 0.0, places=5)

    def test_heading_cardinal_directions(self):
        # 0 deg: UP (0, -1)
        self.ship.angle = 0.0
        hx, hy = self.ship.get_heading()
        self.assertAlmostEqual(hx, 0.0, places=5)
        self.assertAlmostEqual(hy, -1.0, places=5)

        # 90 deg: RIGHT (1, 0)
        self.ship.angle = 90.0
        hx, hy = self.ship.get_heading()
        self.assertAlmostEqual(hx, 1.0, places=5)
        self.assertAlmostEqual(hy, 0.0, places=5)

        # 180 deg: DOWN (0, 1)
        self.ship.angle = 180.0
        hx, hy = self.ship.get_heading()
        self.assertAlmostEqual(hx, 0.0, places=5)
        self.assertAlmostEqual(hy, 1.0, places=5)

        # 270 deg: LEFT (-1, 0)
        self.ship.angle = 270.0
        hx, hy = self.ship.get_heading()
        self.assertAlmostEqual(hx, -1.0, places=5)
        self.assertAlmostEqual(hy, 0.0, places=5)


class TestInertiaThrustPhysics(unittest.TestCase):
    """Verify thrust acceleration, speed capping, and pure inertia drift."""
    def setUp(self):
        self.ship = Ship(x=400, y=300, angle=0.0, friction=1.0)

    def test_initial_state_at_rest(self):
        self.assertEqual(self.ship.velocity_x, 0.0)
        self.assertEqual(self.ship.velocity_y, 0.0)
        self.assertEqual(self.ship.vx, 0.0)
        self.assertEqual(self.ship.vy, 0.0)

    def test_thrust_facing_up(self):
        self.ship.angle = 0.0
        self.ship.thrust()
        self.assertAlmostEqual(self.ship.velocity_x, 0.0, places=5)
        self.assertAlmostEqual(self.ship.velocity_y, -self.ship.thrust_power, places=5)
        self.assertTrue(self.ship.is_thrusting)

    def test_thrust_facing_right(self):
        self.ship.angle = 90.0
        self.ship.thrust()
        self.assertAlmostEqual(self.ship.velocity_x, self.ship.thrust_power, places=5)
        self.assertAlmostEqual(self.ship.velocity_y, 0.0, places=5)

    def test_inertia_persistence_without_friction(self):
        """When friction is 1.0 (pure space inertia), velocity does not decay."""
        self.ship.angle = 0.0
        self.ship.thrust(power=2.0)
        vx = self.ship.velocity_x
        vy = self.ship.velocity_y
        initial_y = self.ship.y

        # Update several times without thrusting
        for step in range(1, 6):
            self.ship.update()
            # Velocity must be strictly preserved
            self.assertEqual(self.ship.velocity_x, vx)
            self.assertEqual(self.ship.velocity_y, vy)
            # Position advances by velocity
            expected_y = (initial_y + vy * step) % self.ship.screen_height
            self.assertAlmostEqual(self.ship.y, expected_y, places=5)

    def test_max_speed_capping(self):
        self.ship.angle = 90.0
        # Apply excessive thrust
        for _ in range(100):
            self.ship.thrust(power=2.0)

        speed = math.hypot(self.ship.velocity_x, self.ship.velocity_y)
        self.assertAlmostEqual(speed, self.ship.max_speed, places=5)

    def test_velocity_properties(self):
        self.ship.vx = 3.5
        self.ship.vy = -4.5
        self.assertEqual(self.ship.velocity_x, 3.5)
        self.assertEqual(self.ship.velocity_y, -4.5)


class TestScreenWrapping(unittest.TestCase):
    """Verify coordinate wrap-around mechanics for all entities and helpers."""
    def test_wrap_position_utility(self):
        # Inside bounds
        self.assertEqual(wrap_position(100, 200, 800, 600), (100, 200))
        # Exceeding right boundary
        self.assertEqual(wrap_position(805, 100, 800, 600), (5, 100))
        # Negative left boundary
        self.assertEqual(wrap_position(-10, 100, 800, 600), (790, 100))
        # Exceeding bottom boundary
        self.assertEqual(wrap_position(100, 615, 800, 600), (100, 15))
        # Negative top boundary
        self.assertEqual(wrap_position(100, -25, 800, 600), (100, 575))

    def test_ship_screen_wrap(self):
        ship = Ship(x=795, y=595, screen_width=800, screen_height=600)
        ship.velocity_x = 10
        ship.velocity_y = 10
        ship.update()
        self.assertEqual(ship.x, 5)
        self.assertEqual(ship.y, 5)

        # Reverse direction across top/left
        ship.velocity_x = -10
        ship.velocity_y = -10
        ship.update()
        self.assertEqual(ship.x, 795)
        self.assertEqual(ship.y, 595)

    def test_asteroid_screen_wrap(self):
        asteroid = Asteroid(x=1, y=1, velocity_x=-5, velocity_y=-5, screen_width=800, screen_height=600)
        asteroid.update()
        self.assertEqual(asteroid.x, 796)
        self.assertEqual(asteroid.y, 596)

    def test_laser_screen_wrap(self):
        laser = Laser(x=798, y=300, velocity_x=10, velocity_y=0, screen_width=800, screen_height=600)
        laser.update()
        self.assertEqual(laser.x, 8)


class TestSplittingRockAsteroids(unittest.TestCase):
    """Verify asteroid sizes, radii, score values, and splitting progression."""
    def test_asteroid_stages_radii_and_scores(self):
        large = Asteroid(stage=ASTEROID_LARGE)
        self.assertEqual(large.stage, 3)
        self.assertEqual(large.radius, ASTEROID_RADII[ASTEROID_LARGE])
        self.assertEqual(large.score_value, ASTEROID_SCORES[ASTEROID_LARGE])
        self.assertEqual(large.points, 20)
        self.assertEqual(large.size, 3)
        self.assertEqual(large.size, "large")

        medium = Asteroid(stage=ASTEROID_MEDIUM)
        self.assertEqual(medium.stage, 2)
        self.assertEqual(medium.radius, ASTEROID_RADII[ASTEROID_MEDIUM])
        self.assertEqual(medium.score_value, ASTEROID_SCORES[ASTEROID_MEDIUM])
        self.assertEqual(medium.points, 50)
        self.assertEqual(medium.size, 2)
        self.assertEqual(medium.size, "medium")

        small = Asteroid(stage=ASTEROID_SMALL)
        self.assertEqual(small.stage, 1)
        self.assertEqual(small.radius, ASTEROID_RADII[ASTEROID_SMALL])
        self.assertEqual(small.score_value, ASTEROID_SCORES[ASTEROID_SMALL])
        self.assertEqual(small.points, 100)
        self.assertEqual(small.size, 1)
        self.assertEqual(small.size, "small")

    def test_large_asteroid_split(self):
        large = Asteroid(x=300, y=200, stage=ASTEROID_LARGE, velocity_x=1.0, velocity_y=1.0)
        children = large.split()
        self.assertEqual(len(children), 2)
        self.assertFalse(large.is_alive)
        self.assertFalse(large.alive)
        for child in children:
            self.assertEqual(child.stage, ASTEROID_MEDIUM)
            self.assertEqual(child.radius, ASTEROID_RADII[ASTEROID_MEDIUM])
            self.assertEqual(child.score_value, 50)
            self.assertEqual(child.x, 300)
            self.assertEqual(child.y, 200)
            self.assertTrue(child.is_alive)

    def test_medium_asteroid_split(self):
        medium = Asteroid(x=150, y=250, stage=ASTEROID_MEDIUM, velocity_x=2.0, velocity_y=0.0)
        children = medium.split()
        self.assertEqual(len(children), 2)
        self.assertFalse(medium.is_alive)
        for child in children:
            self.assertEqual(child.stage, ASTEROID_SMALL)
            self.assertEqual(child.radius, ASTEROID_RADII[ASTEROID_SMALL])
            self.assertEqual(child.score_value, 100)
            self.assertTrue(child.is_alive)

    def test_small_asteroid_split_destroys(self):
        small = Asteroid(x=100, y=100, stage=ASTEROID_SMALL)
        children = small.split()
        self.assertEqual(children, [])
        self.assertFalse(small.is_alive)

    def test_repeat_split_on_dead_asteroid(self):
        large = Asteroid(stage=ASTEROID_LARGE)
        large.split()
        # Second call should safely return empty list
        self.assertEqual(large.split(), [])


class TestLaserShooting(unittest.TestCase):
    """Verify laser spawning, velocity vectors, firing cooldown, and lifetime expiry."""
    def setUp(self):
        self.ship = Ship(x=400, y=300, angle=0.0)

    def test_fire_laser_direction(self):
        self.ship.angle = 90.0  # Facing right
        laser = self.ship.shoot(speed=10.0)
        self.assertIsNotNone(laser)
        self.assertEqual(laser.angle, 90.0)
        self.assertAlmostEqual(laser.velocity_x, 10.0, places=5)
        self.assertAlmostEqual(laser.velocity_y, 0.0, places=5)

    def test_bullet_alias(self):
        self.assertIs(Bullet, Laser)
        bullet = Bullet(x=10, y=20, velocity_x=1, velocity_y=2)
        self.assertEqual(bullet.x, 10)
        self.assertEqual(bullet.vx, 1)

    def test_fire_cooldown(self):
        laser1 = self.ship.shoot()
        self.assertIsNotNone(laser1)
        # Immediate second shot blocked by cooldown
        laser2 = self.ship.shoot()
        self.assertIsNone(laser2)

        # Wait out cooldown
        for _ in range(self.ship.fire_cooldown_max):
            self.ship.update()

        laser3 = self.ship.shoot()
        self.assertIsNotNone(laser3)

    def test_laser_lifetime_expiry(self):
        laser = Laser(x=100, y=100, angle=0.0, lifetime=5)
        self.assertTrue(laser.is_alive)
        for _ in range(5):
            laser.update()
        self.assertFalse(laser.is_alive)
        self.assertFalse(laser.alive)


class TestScoreTracking(unittest.TestCase):
    """Verify score addition, high score tracking, and score reset."""
    def setUp(self):
        self.game = AsteroidsGame(initial_asteroids=0, headless=True)

    def test_initial_score(self):
        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.high_score, 0)
        self.assertEqual(self.game.get_score(), 0)

    def test_add_score_and_high_score(self):
        self.game.add_score(20)
        self.assertEqual(self.game.score, 20)
        self.assertEqual(self.game.high_score, 20)

        self.game.add_score(50)
        self.assertEqual(self.game.score, 70)
        self.assertEqual(self.game.high_score, 70)

    def test_score_awarded_on_asteroid_hit(self):
        # Spawn one large asteroid and a laser colliding with it
        asteroid = Asteroid(x=200, y=200, stage=ASTEROID_LARGE)
        laser = Laser(x=200, y=200)
        self.game.asteroids = [asteroid]
        self.game.lasers = [laser]

        self.game.update()

        # Large asteroid awards 20 points and splits into 2 medium asteroids
        self.assertEqual(self.game.score, 20)
        self.assertEqual(len(self.game.asteroids), 2)
        self.assertEqual(len(self.game.lasers), 0)

    def test_destroying_all_stages_score_sum(self):
        # Destroy large (20), medium (50), small (100)
        for stage, expected_points in [(ASTEROID_LARGE, 20), (ASTEROID_MEDIUM, 50), (ASTEROID_SMALL, 100)]:
            prev_score = self.game.score
            asteroid = Asteroid(x=300, y=300, stage=stage)
            laser = Laser(x=300, y=300)
            self.game.asteroids = [asteroid]
            self.game.lasers = [laser]
            self.game.update()
            self.assertEqual(self.game.score - prev_score, expected_points)


class TestCollisionDetection(unittest.TestCase):
    """Verify entity circular collision detection, lives decrement, and game over."""
    def setUp(self):
        self.game = AsteroidsGame(initial_asteroids=0, headless=True)

    def test_collision_circle_overlap(self):
        ship = Ship(x=100, y=100, radius=15)
        asteroid = Asteroid(x=120, y=100, radius=20)
        # Distance is 20 < 15 + 20 (35) -> collision
        self.assertTrue(ship.collides_with(asteroid))
        self.assertTrue(asteroid.collides_with(ship))

    def test_collision_no_overlap(self):
        ship = Ship(x=100, y=100, radius=15)
        asteroid = Asteroid(x=200, y=200, radius=20)
        self.assertFalse(ship.collides_with(asteroid))

    def test_ship_vulnerable_collision_loses_life(self):
        self.game.ship.x = 400
        self.game.ship.y = 300
        self.game.ship.invulnerable_timer = 0
        self.game.lives = 3

        asteroid = Asteroid(x=400, y=300, stage=ASTEROID_LARGE)
        self.game.asteroids = [asteroid]

        self.game.update()

        self.assertEqual(self.game.lives, 2)
        self.assertFalse(self.game.game_over)
        self.assertTrue(self.game.ship.is_invulnerable())

    def test_ship_invulnerable_collision_protects_life(self):
        self.game.ship.x = 400
        self.game.ship.y = 300
        self.game.ship.invulnerable_timer = 60
        self.game.lives = 3

        asteroid = Asteroid(x=400, y=300, stage=ASTEROID_LARGE)
        self.game.asteroids = [asteroid]

        self.game.update()

        # No lives lost while invulnerable
        self.assertEqual(self.game.lives, 3)

    def test_game_over_when_lives_exhausted(self):
        self.game.ship.x = 400
        self.game.ship.y = 300
        self.game.ship.invulnerable_timer = 0
        self.game.lives = 1

        asteroid = Asteroid(x=400, y=300, stage=ASTEROID_LARGE)
        self.game.asteroids = [asteroid]

        self.game.update()

        self.assertEqual(self.game.lives, 0)
        self.assertTrue(self.game.game_over)
        self.assertTrue(self.game.is_game_over())


class TestGameWaveProgression(unittest.TestCase):
    """Verify level progression when wave is cleared, aliases, and reset."""
    def setUp(self):
        self.game = AsteroidsGame(initial_asteroids=0, headless=True)

    def test_wave_cleared_increments_level(self):
        self.assertEqual(self.game.level, 1)
        self.assertEqual(len(self.game.asteroids), 0)

        # Trigger update with 0 asteroids
        self.game.update()

        self.assertEqual(self.game.level, 2)
        self.assertGreater(len(self.game.asteroids), 0)

    def test_bullets_property_alias(self):
        laser = Laser(10, 20)
        self.game.bullets = [laser]
        self.assertEqual(self.game.lasers, [laser])
        self.assertEqual(self.game.bullets, [laser])

    def test_game_class_alias(self):
        self.assertIs(Game, AsteroidsGame)
        instance = Game(initial_asteroids=2, headless=True)
        self.assertEqual(len(instance.asteroids), 2)

    def test_game_reset(self):
        self.game.score = 500
        self.game.lives = 0
        self.game.level = 4
        self.game.game_over = True
        self.game.asteroids = [Asteroid()]
        self.game.lasers = [Laser(10, 10)]

        self.game.reset()

        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.lives, 3)
        self.assertEqual(self.game.level, 1)
        self.assertFalse(self.game.game_over)
        self.assertEqual(len(self.game.lasers), 0)
        self.assertEqual(len(self.game.asteroids), 4)


if __name__ == "__main__":
    unittest.main()
