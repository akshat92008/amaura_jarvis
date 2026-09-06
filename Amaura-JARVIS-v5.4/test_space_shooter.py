"""
Comprehensive Unit and Integration Tests for Space Shooter Arcade Game.
"""

import os
import sys

# Ensure headless execution for Pygame
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import unittest
import pygame

import space_shooter
from space_shooter import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    GameState,
    PowerUpType,
    EnemyType,
    Player,
    Enemy,
    Laser,
    PowerUp,
    Particle,
    Star,
    SpaceShooterGame,
    Game,
    create_player_surface,
    create_laser_surface,
    create_enemy_surface,
    create_powerup_surface,
    init_pygame,
)


class TestGameConstants(unittest.TestCase):
    def test_screen_dimensions(self):
        self.assertEqual(SCREEN_WIDTH, 800)
        self.assertEqual(SCREEN_HEIGHT, 600)

    def test_game_states(self):
        self.assertEqual(GameState.MENU, "MENU")
        self.assertEqual(GameState.PLAYING, "PLAYING")
        self.assertEqual(GameState.PAUSED, "PAUSED")
        self.assertEqual(GameState.GAME_OVER, "GAME_OVER")

    def test_enemy_types(self):
        self.assertEqual(EnemyType.SCOUT, "SCOUT")
        self.assertEqual(EnemyType.FIGHTER, "FIGHTER")
        self.assertEqual(EnemyType.BOMBER, "BOMBER")
        self.assertEqual(EnemyType.BOSS, "BOSS")

    def test_powerup_types(self):
        expected_types = {"HEALTH", "SHIELD", "DOUBLE_SHOT", "TRIPLE_SHOT", "SPEED_BOOST", "BOMB"}
        self.assertEqual(set(PowerUpType.ALL_TYPES), expected_types)


class TestProceduralSurfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def test_player_surface(self):
        surf = create_player_surface(40, 40)
        self.assertIsInstance(surf, pygame.Surface)
        self.assertEqual(surf.get_size(), (40, 40))

    def test_laser_surface(self):
        surf = create_laser_surface(4, 14)
        self.assertIsInstance(surf, pygame.Surface)
        self.assertEqual(surf.get_size(), (4, 14))

    def test_enemy_surfaces(self):
        for et in [EnemyType.SCOUT, EnemyType.FIGHTER, EnemyType.BOMBER, EnemyType.BOSS]:
            surf = create_enemy_surface(32, 32, et)
            self.assertIsInstance(surf, pygame.Surface)
            self.assertEqual(surf.get_size(), (32, 32))

    def test_powerup_surfaces(self):
        for pt in PowerUpType.ALL_TYPES:
            surf = create_powerup_surface(24, 24, pt)
            self.assertIsInstance(surf, pygame.Surface)
            self.assertEqual(surf.get_size(), (24, 24))


class TestPlayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def setUp(self):
        self.player = Player(400, 500)

    def test_initial_state(self):
        self.assertEqual(self.player.health, 100)
        self.assertEqual(self.player.max_health, 100)
        self.assertEqual(self.player.lives, 3)
        self.assertEqual(self.player.score, 0)
        self.assertEqual(self.player.weapon_level, 1)
        self.assertTrue(self.player.alive)
        self.assertEqual(self.player.speed, 5.0)
        self.assertFalse(self.player.invulnerable)
        self.assertEqual(self.player.shield, 0)

    def test_movement(self):
        init_x = self.player.rect.x
        init_y = self.player.rect.y

        self.player.move_left()
        self.assertEqual(self.player.rect.x, init_x - int(self.player.speed))

        self.player.move_right()
        self.assertEqual(self.player.rect.x, init_x)

        self.player.move_up()
        self.assertEqual(self.player.rect.y, init_y - int(self.player.speed))

        self.player.move_down()
        self.assertEqual(self.player.rect.y, init_y)

    def test_boundary_constraints(self):
        # Move far to the left
        self.player.move(-1000, 0)
        self.assertEqual(self.player.rect.left, 0)

        # Move far to the right
        self.player.move(2000, 0)
        self.assertEqual(self.player.rect.right, SCREEN_WIDTH)

        # Move far up
        self.player.move(0, -1000)
        self.assertEqual(self.player.rect.top, 0)

        # Move far down
        self.player.move(0, 2000)
        self.assertEqual(self.player.rect.bottom, SCREEN_HEIGHT)

    def test_single_shot(self):
        self.player.weapon_level = 1
        lasers = self.player.shoot(current_time=1000)
        self.assertEqual(len(lasers), 1)
        laser = lasers[0]
        self.assertTrue(laser.is_player)
        self.assertEqual(laser.rect.centerx, self.player.rect.centerx)
        self.assertLess(laser.speed_y, 0)

    def test_double_shot(self):
        self.player.weapon_level = 2
        lasers = self.player.shoot(current_time=1000)
        self.assertEqual(len(lasers), 2)
        self.assertNotEqual(lasers[0].rect.centerx, lasers[1].rect.centerx)

    def test_triple_shot(self):
        self.player.weapon_level = 3
        lasers = self.player.shoot(current_time=1000)
        self.assertEqual(len(lasers), 3)
        # Center straight, left angled, right angled
        speed_xs = [l.speed_x for l in lasers]
        self.assertIn(0.0, speed_xs)
        self.assertTrue(any(sx < 0 for sx in speed_xs))
        self.assertTrue(any(sx > 0 for sx in speed_xs))

    def test_shoot_cooldown(self):
        lasers1 = self.player.shoot(current_time=1000)
        self.assertGreater(len(lasers1), 0)

        # Shot within cooldown delay returns nothing
        lasers2 = self.player.shoot(current_time=1050)
        self.assertEqual(len(lasers2), 0)

        # Shot after delay succeeds
        lasers3 = self.player.shoot(current_time=1000 + self.player.shoot_delay + 10)
        self.assertGreater(len(lasers3), 0)

    def test_take_damage_health(self):
        dmg = self.player.take_damage(30)
        self.assertEqual(dmg, 30)
        self.assertEqual(self.player.health, 70)
        self.assertTrue(self.player.invulnerable)

    def test_take_damage_shield(self):
        self.player.activate_shield(amount=50)
        self.assertEqual(self.player.shield, 50)

        # Partial shield absorption
        dmg1 = self.player.take_damage(30)
        self.assertEqual(dmg1, 30)
        self.assertEqual(self.player.shield, 20)
        self.assertEqual(self.player.health, 100)

        # Over-shield damage: clear invulnerability first for test
        self.player.invulnerable = False
        dmg2 = self.player.take_damage(40)
        self.assertEqual(dmg2, 40)
        self.assertEqual(self.player.shield, 0)
        self.assertEqual(self.player.health, 80)

    def test_invulnerability_blocks_damage(self):
        self.player.invulnerable = True
        dmg = self.player.take_damage(50)
        self.assertEqual(dmg, 0)
        self.assertEqual(self.player.health, 100)

        # Updating past timer expires invulnerability
        self.player.invulnerable_timer = 300.0
        self.player.update(dt=0.4)
        self.assertFalse(self.player.invulnerable)

    def test_life_loss_and_respawn(self):
        self.player.invulnerable = False
        self.player.take_damage(100)
        self.assertEqual(self.player.lives, 2)
        self.assertEqual(self.player.health, 100)
        self.assertTrue(self.player.invulnerable)
        self.assertTrue(self.player.alive)

    def test_loss_of_all_lives(self):
        self.player.lives = 1
        self.player.invulnerable = False
        self.player.take_damage(100)
        self.assertEqual(self.player.lives, 0)
        self.assertEqual(self.player.health, 0)
        self.assertFalse(self.player.alive)

    def test_heal(self):
        self.player.health = 50
        healed = self.player.heal(30)
        self.assertEqual(healed, 30)
        self.assertEqual(self.player.health, 80)

        # Capped at max_health
        healed2 = self.player.heal(50)
        self.assertEqual(healed2, 20)
        self.assertEqual(self.player.health, 100)

    def test_score_addition(self):
        self.player.add_score(250)
        self.assertEqual(self.player.score, 250)

    def test_buff_expirations(self):
        self.player.upgrade_weapon(level=3, duration=0.1)
        self.player.activate_speed_boost(multiplier=2.0, duration=0.1)
        self.player.activate_shield(amount=50, duration=0.1)

        self.assertEqual(self.player.weapon_level, 3)
        self.assertEqual(self.player.speed, 10.0)
        self.assertEqual(self.player.shield, 50)

        # Advance past 0.1s
        self.player.update(dt=0.2)
        self.assertEqual(self.player.weapon_level, 1)
        self.assertEqual(self.player.speed, self.player.base_speed)
        self.assertEqual(self.player.shield, 0)

    def test_player_reset(self):
        self.player.health = 20
        self.player.score = 500
        self.player.lives = 1
        self.player.reset(full=True)
        self.assertEqual(self.player.health, 100)
        self.assertEqual(self.player.score, 0)
        self.assertEqual(self.player.lives, 3)
        self.assertTrue(self.player.alive)


class TestLaser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def test_laser_init_and_movement(self):
        laser = Laser(100, 200, speed_y=-10.0, speed_x=2.0, damage=20, is_player=True)
        self.assertTrue(laser.is_player)
        self.assertEqual(laser.damage, 20)

        laser.update(dt=1/60)
        self.assertEqual(laser.rect.centery, 190)
        self.assertEqual(laser.rect.centerx, 102)

    def test_laser_off_screen(self):
        laser_top = Laser(100, -20)
        self.assertTrue(laser_top.is_off_screen())

        laser_bottom = Laser(100, SCREEN_HEIGHT + 20)
        self.assertTrue(laser_bottom.is_off_screen())

        laser_inside = Laser(100, 300)
        self.assertFalse(laser_inside.is_off_screen())

        laser_top.update()
        self.assertFalse(laser_top.alive())


class TestEnemy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def test_enemy_types_initialization(self):
        scout = Enemy(100, 100, EnemyType.SCOUT)
        self.assertEqual(scout.health, 20)
        self.assertEqual(scout.points, 100)
        self.assertFalse(scout.can_shoot)

        fighter = Enemy(100, 100, EnemyType.FIGHTER)
        self.assertEqual(fighter.health, 40)
        self.assertEqual(fighter.points, 200)
        self.assertTrue(fighter.can_shoot)

        bomber = Enemy(100, 100, EnemyType.BOMBER)
        self.assertEqual(bomber.health, 80)
        self.assertEqual(bomber.points, 350)
        self.assertTrue(bomber.can_shoot)

        boss = Enemy(100, 100, EnemyType.BOSS, level=1)
        self.assertGreaterEqual(boss.health, 450)
        self.assertEqual(boss.points, 2000)
        self.assertTrue(boss.can_shoot)

    def test_enemy_movement(self):
        enemy = Enemy(200, 100, EnemyType.SCOUT)
        init_y = enemy.rect.centery
        enemy.update(dt=1/60)
        self.assertGreater(enemy.rect.centery, init_y)

    def test_enemy_take_damage_and_death(self):
        enemy = Enemy(200, 100, EnemyType.SCOUT)
        killed = enemy.take_damage(10)
        self.assertFalse(killed)
        self.assertEqual(enemy.health, 10)
        self.assertTrue(enemy.alive)

        killed2 = enemy.take_damage(10)
        self.assertTrue(killed2)
        self.assertEqual(enemy.health, 0)
        self.assertFalse(enemy.alive)

    def test_enemy_shooting(self):
        scout = Enemy(200, 100, EnemyType.SCOUT)
        self.assertEqual(len(scout.shoot(current_time=5000)), 0)

        fighter = Enemy(200, 100, EnemyType.FIGHTER)
        fighter.last_shot_time = 0
        lasers = fighter.shoot(current_time=3000)
        self.assertGreaterEqual(len(lasers), 1)
        self.assertFalse(lasers[0].is_player)

        boss = Enemy(200, 100, EnemyType.BOSS)
        boss.last_shot_time = 0
        boss_lasers = boss.shoot(current_time=3000)
        self.assertEqual(len(boss_lasers), 3)

    def test_enemy_off_screen(self):
        enemy = Enemy(200, SCREEN_HEIGHT + 50, EnemyType.SCOUT)
        self.assertTrue(enemy.is_off_screen())
        enemy.update()
        is_alive = enemy.alive if isinstance(enemy.alive, bool) else enemy.alive()
        self.assertFalse(is_alive)


class TestPowerUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def setUp(self):
        self.player = Player(400, 500)

    def test_powerup_movement(self):
        p = PowerUp(200, 100, PowerUpType.HEALTH, speed_y=3.0)
        p.update(dt=1/60)
        self.assertEqual(p.rect.centery, 103)

    def test_apply_health_powerup(self):
        self.player.health = 50
        p = PowerUp(400, 500, PowerUpType.HEALTH)
        p.apply(self.player)
        self.assertEqual(self.player.health, 80)
        self.assertFalse(p.alive())

    def test_apply_health_powerup_bonus_score_at_full(self):
        self.player.health = 100
        p = PowerUp(400, 500, PowerUpType.HEALTH)
        p.apply(self.player)
        self.assertEqual(self.player.score, 500)

    def test_apply_shield_powerup(self):
        p = PowerUp(400, 500, PowerUpType.SHIELD)
        p.apply(self.player)
        self.assertEqual(self.player.shield, 100)

    def test_apply_weapon_upgrades(self):
        p2 = PowerUp(400, 500, PowerUpType.DOUBLE_SHOT)
        p2.apply(self.player)
        self.assertEqual(self.player.weapon_level, 2)

        p3 = PowerUp(400, 500, PowerUpType.TRIPLE_SHOT)
        p3.apply(self.player)
        self.assertEqual(self.player.weapon_level, 3)

    def test_apply_speed_boost(self):
        p = PowerUp(400, 500, PowerUpType.SPEED_BOOST)
        p.apply(self.player)
        self.assertGreater(self.player.speed, self.player.base_speed)


class TestParticlesAndStars(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def test_particle_lifecycle(self):
        p = Particle(100, 100, vx=1.0, vy=1.0, lifetime=2)
        group = pygame.sprite.Group(p)
        p.update(dt=1/60)
        self.assertTrue(p.alive())
        p.update(dt=1/60)
        self.assertFalse(p.alive())

    def test_star_update(self):
        star = Star(x=100, y=SCREEN_HEIGHT - 1, width=SCREEN_WIDTH, height=SCREEN_HEIGHT)
        star.update()
        if star.y > SCREEN_HEIGHT:
            star.update()
            self.assertLessEqual(star.y, SCREEN_HEIGHT)


class TestSpaceShooterGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_pygame()

    def setUp(self):
        self.game = SpaceShooterGame()

    def test_initial_state(self):
        self.assertEqual(self.game.state, GameState.MENU)
        self.assertIsNotNone(self.game.player)
        self.assertEqual(len(self.game.enemies), 0)
        self.assertEqual(len(self.game.player_lasers), 0)

    def test_start_and_pause(self):
        self.game.start_game()
        self.assertEqual(self.game.state, GameState.PLAYING)

        self.game.pause_game()
        self.assertEqual(self.game.state, GameState.PAUSED)

        self.game.pause_game()
        self.assertEqual(self.game.state, GameState.PLAYING)

    def test_game_over(self):
        self.game.start_game()
        self.game.player.score = 800
        self.game.game_over()
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.assertEqual(self.game.high_score, 800)

    def test_spawn_enemy(self):
        enemy = self.game.spawn_enemy(EnemyType.SCOUT, x=200, y=50)
        self.assertIn(enemy, self.game.enemies)
        self.assertIn(enemy, self.game.all_sprites)

    def test_spawn_powerup(self):
        p = self.game.spawn_powerup(200, 200, PowerUpType.HEALTH)
        self.assertIn(p, self.game.powerups)
        self.assertIn(p, self.game.all_sprites)

    def test_player_laser_kills_enemy_and_adds_score(self):
        self.game.start_game()
        enemy = self.game.spawn_enemy(EnemyType.SCOUT, x=400, y=200)
        enemy.health = 10  # 1 hit kill

        laser = Laser(400, 200, damage=15, is_player=True)
        self.game.player_lasers.add(laser)
        self.game.all_sprites.add(laser)

        init_score = self.game.player.score
        self.game.update(dt=1/60)

        self.assertNotIn(enemy, self.game.enemies)
        self.assertGreater(self.game.player.score, init_score)
        self.assertEqual(self.game.enemies_killed, 1)

    def test_enemy_laser_damages_player(self):
        self.game.start_game()
        self.game.player.invulnerable = False
        init_health = self.game.player.health

        laser = Laser(self.game.player.rect.centerx, self.game.player.rect.centery, damage=15, is_player=False)
        self.game.enemy_lasers.add(laser)
        self.game.all_sprites.add(laser)

        self.game.update(dt=1/60)
        self.assertLess(self.game.player.health, init_health)
        self.assertNotIn(laser, self.game.enemy_lasers)

    def test_ship_collision(self):
        self.game.start_game()
        self.game.player.invulnerable = False
        enemy = self.game.spawn_enemy(EnemyType.FIGHTER, x=self.game.player.rect.centerx, y=self.game.player.rect.centery)

        init_health = self.game.player.health
        self.game.update(dt=1/60)

        self.assertLess(self.game.player.health, init_health)

    def test_player_collects_powerup(self):
        self.game.start_game()
        self.game.player.health = 50
        p = self.game.spawn_powerup(self.game.player.rect.centerx, self.game.player.rect.centery, PowerUpType.HEALTH)

        self.game.update(dt=1/60)
        self.assertEqual(self.game.player.health, 80)
        self.assertNotIn(p, self.game.powerups)

    def test_trigger_bomb(self):
        self.game.start_game()
        e1 = self.game.spawn_enemy(EnemyType.SCOUT, 200, 100)
        e2 = self.game.spawn_enemy(EnemyType.FIGHTER, 400, 100)
        l = Laser(300, 100, is_player=False)
        self.game.enemy_lasers.add(l)

        self.game.trigger_bomb()
        self.assertNotIn(e1, self.game.enemies)
        self.assertNotIn(e2, self.game.enemies)
        self.assertNotIn(l, self.game.enemy_lasers)

    def test_boss_spawn_and_defeat(self):
        self.game.start_game()
        boss = self.game.spawn_boss()
        self.assertTrue(self.game.boss_active)
        self.assertIn(boss, self.game.enemies)

        # Defeat boss
        boss.take_damage(boss.health)
        self.game.enemies.remove(boss)
        self.game.boss_active = False
        self.game.current_boss = None
        self.game.wave += 1

        self.assertFalse(self.game.boss_active)
        self.assertIsNone(self.game.current_boss)
        self.assertEqual(self.game.wave, 2)

    def test_handle_event(self):
        # Start game with SPACE in MENU
        evt_start = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        self.game.handle_event(evt_start)
        self.assertEqual(self.game.state, GameState.PLAYING)

        # Pause with P
        evt_pause = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p)
        self.game.handle_event(evt_pause)
        self.assertEqual(self.game.state, GameState.PAUSED)

        # Resume with P
        self.game.handle_event(evt_pause)
        self.assertEqual(self.game.state, GameState.PLAYING)

        # Shoot with SPACE
        laser_count = len(self.game.player_lasers)
        evt_shoot = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
        self.game.handle_event(evt_shoot)
        self.assertGreater(len(self.game.player_lasers), laser_count)

        # Game over and restart
        self.game.game_over()
        self.assertEqual(self.game.state, GameState.GAME_OVER)
        self.game.handle_event(evt_start)
        self.assertEqual(self.game.state, GameState.PLAYING)

    def test_handle_input_continuous(self):
        self.game.start_game()
        init_x = self.game.player.rect.x

        keys = {
            pygame.K_LEFT: True,
            pygame.K_RIGHT: False,
            pygame.K_UP: False,
            pygame.K_DOWN: False,
            pygame.K_a: False,
            pygame.K_d: False,
            pygame.K_w: False,
            pygame.K_s: False,
            pygame.K_SPACE: False,
        }
        self.game.handle_input(keys)
        self.assertLess(self.game.player.rect.x, init_x)

    def test_step_and_draw_headless(self):
        self.game.start_game()
        # Step frame
        self.game.step(dt=1/60)

        # Headless drawing verification
        dummy_screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        for state in [GameState.MENU, GameState.PLAYING, GameState.PAUSED, GameState.GAME_OVER]:
            self.game.state = state
            # Should render all HUD, overlays, and sprites cleanly without error
            self.game.draw(dummy_screen)


if __name__ == "__main__":
    unittest.main()
