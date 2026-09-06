"""
Space Shooter Arcade Game
Implemented with Pygame.
"""

import os
import sys
import math
import random

# Headless fallback: ensure pygame runs cleanly in environments without an active display
if "SDL_VIDEODRIVER" not in os.environ and "DISPLAY" not in os.environ and sys.platform != "darwin":
    os.environ["SDL_VIDEODRIVER"] = "dummy"
if "SDL_AUDIODRIVER" not in os.environ:
    os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

# Screen settings
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Color definitions (RGB)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 50, 50)
GREEN = (50, 255, 50)
BLUE = (50, 150, 255)
YELLOW = (255, 255, 50)
ORANGE = (255, 165, 0)
CYAN = (0, 255, 255)
PURPLE = (180, 50, 255)
DARK_GRAY = (40, 40, 40)
GRAY = (128, 128, 128)
LIGHT_BLUE = (100, 200, 255)


class GameState:
    MENU = "MENU"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"


class PowerUpType:
    HEALTH = "HEALTH"
    SHIELD = "SHIELD"
    DOUBLE_SHOT = "DOUBLE_SHOT"
    TRIPLE_SHOT = "TRIPLE_SHOT"
    SPEED_BOOST = "SPEED_BOOST"
    BOMB = "BOMB"
    ALL_TYPES = [HEALTH, SHIELD, DOUBLE_SHOT, TRIPLE_SHOT, SPEED_BOOST, BOMB]


class EnemyType:
    SCOUT = "SCOUT"
    FIGHTER = "FIGHTER"
    BOMBER = "BOMBER"
    BOSS = "BOSS"


def init_pygame():
    """Safely initialize pygame modules with fallback for headless environments."""
    if not pygame.get_init():
        try:
            pygame.init()
        except Exception:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
            pygame.init()
    if not pygame.font.get_init():
        try:
            pygame.font.init()
        except Exception:
            pass


def create_screen(width=SCREEN_WIDTH, height=SCREEN_HEIGHT):
    """Creates a display surface, falling back to dummy video driver if needed."""
    init_pygame()
    try:
        return pygame.display.set_mode((width, height))
    except pygame.error:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        pygame.display.init()
        return pygame.display.set_mode((width, height))


def get_font(size):
    """Retrieves a pygame font safely across platforms."""
    if not pygame.font.get_init():
        try:
            pygame.font.init()
        except Exception:
            return None
    try:
        return pygame.font.Font(None, size)
    except Exception:
        try:
            return pygame.font.SysFont("Arial", size)
        except Exception:
            return None


def render_text(surface, text, font, color, center_pos=None, top_left=None):
    """Renders text safely onto the target surface."""
    if font is None or surface is None:
        return
    try:
        txt_surf = font.render(str(text), True, color)
        if center_pos:
            rect = txt_surf.get_rect(center=center_pos)
            surface.blit(txt_surf, rect)
        elif top_left:
            surface.blit(txt_surf, top_left)
    except Exception:
        pass


def create_player_surface(width=40, height=40):
    """Generates a sleek player starship surface with transparent background."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    hull_pts = [
        (width // 2, 2),
        (width - 4, height - 8),
        (width - 10, height - 14),
        (width // 2 + 5, height - 4),
        (width // 2 - 5, height - 4),
        (10, height - 14),
        (4, height - 8),
    ]
    pygame.draw.polygon(surf, BLUE, hull_pts)
    pygame.draw.polygon(surf, CYAN, [
        (width // 2, 8),
        (width // 2 + 6, height - 12),
        (width // 2 - 6, height - 12)
    ])
    pygame.draw.ellipse(surf, WHITE, (width // 2 - 3, 12, 6, 12))
    pygame.draw.circle(surf, ORANGE, (width // 2, height - 4), 3)
    return surf


def create_laser_surface(width=4, height=14, color=CYAN):
    """Generates a glowing laser projectile surface."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(surf, color, (0, 0, width, height), border_radius=max(1, width // 2))
    inner_w = max(1, width - 2)
    pygame.draw.rect(surf, WHITE, (1, 2, inner_w, max(1, height - 4)))
    return surf


def create_enemy_surface(width, height, enemy_type, color=RED):
    """Generates procedural alien craft surfaces tailored to each enemy type."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    w, h = width, height
    if enemy_type == EnemyType.SCOUT:
        pts = [
            (w // 2, h - 2),
            (2, 4),
            (w // 2, 10),
            (w - 2, 4)
        ]
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.polygon(surf, ORANGE, [
            (w // 2, h - 8),
            (w // 2 - 4, 8),
            (w // 2 + 4, 8)
        ])
    elif enemy_type == EnemyType.FIGHTER:
        pts = [
            (w // 2, h - 4),
            (w - 2, 8),
            (w - 10, 16),
            (w // 2 + 4, 2),
            (w // 2 - 4, 2),
            (10, 16),
            (2, 8)
        ]
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.circle(surf, RED, (w // 2, h // 2), 5)
    elif enemy_type == EnemyType.BOMBER:
        pts = [
            (w // 2, h - 2),
            (w - 4, h // 2),
            (w - 8, 4),
            (8, 4),
            (4, h // 2)
        ]
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.rect(surf, RED, (w // 2 - 4, h // 2 - 4, 8, 8))
    elif enemy_type == EnemyType.BOSS:
        pts = [
            (w // 2, h - 2),
            (w - 8, h - 20),
            (w - 2, 10),
            (w - 25, 4),
            (w // 2, 18),
            (25, 4),
            (2, 10),
            (8, h - 20)
        ]
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.polygon(surf, ORANGE, [
            (w // 2, h - 14),
            (w - 20, 20),
            (20, 20)
        ])
        pygame.draw.circle(surf, RED, (w // 2, h // 2), 12)
        pygame.draw.circle(surf, YELLOW, (w // 2, h // 2), 6)
    else:
        pts = [(w // 2, h), (0, 0), (w, 0)]
        pygame.draw.polygon(surf, color, pts)
    return surf


def create_powerup_surface(width=24, height=24, power_type=PowerUpType.HEALTH):
    """Generates an arcade capsule icon for powerups."""
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    color_map = {
        PowerUpType.HEALTH: GREEN,
        PowerUpType.SHIELD: CYAN,
        PowerUpType.DOUBLE_SHOT: YELLOW,
        PowerUpType.TRIPLE_SHOT: ORANGE,
        PowerUpType.SPEED_BOOST: BLUE,
        PowerUpType.BOMB: RED,
    }
    bg_color = color_map.get(power_type, WHITE)
    pygame.draw.rect(surf, bg_color, (0, 0, width, height), border_radius=5)
    pygame.draw.rect(surf, WHITE, (2, 2, width - 4, height - 4), width=1, border_radius=4)

    cx, cy = width // 2, height // 2
    if power_type == PowerUpType.HEALTH:
        pygame.draw.line(surf, WHITE, (cx, 5), (cx, height - 5), 3)
        pygame.draw.line(surf, WHITE, (5, cy), (width - 5, cy), 3)
    elif power_type == PowerUpType.SHIELD:
        pygame.draw.circle(surf, WHITE, (cx, cy), 6, 2)
    elif power_type == PowerUpType.DOUBLE_SHOT:
        pygame.draw.line(surf, WHITE, (cx - 3, 6), (cx - 3, height - 6), 2)
        pygame.draw.line(surf, WHITE, (cx + 3, 6), (cx + 3, height - 6), 2)
    elif power_type == PowerUpType.TRIPLE_SHOT:
        pygame.draw.line(surf, WHITE, (cx - 5, 6), (cx - 5, height - 6), 2)
        pygame.draw.line(surf, WHITE, (cx, 6), (cx, height - 6), 2)
        pygame.draw.line(surf, WHITE, (cx + 5, 6), (cx + 5, height - 6), 2)
    elif power_type == PowerUpType.SPEED_BOOST:
        pts = [(cx - 4, 6), (cx + 2, cy), (cx - 4, height - 6)]
        pygame.draw.lines(surf, WHITE, False, pts, 2)
    elif power_type == PowerUpType.BOMB:
        pygame.draw.circle(surf, WHITE, (cx, cy + 2), 5)
        pygame.draw.line(surf, WHITE, (cx, cy - 3), (cx + 3, cy - 6), 2)
    return surf


class Star:
    """Background star for parallax scrolling effect."""
    def __init__(self, x=None, y=None, width=SCREEN_WIDTH, height=SCREEN_HEIGHT):
        self.width = width
        self.height = height
        self.x = random.randint(0, width) if x is None else float(x)
        self.y = random.randint(0, height) if y is None else float(y)
        self.speed = random.uniform(0.5, 2.5)
        self.size = random.choice([1, 1, 2, 2, 3]) if self.speed > 1.5 else 1
        brightness = int(100 + self.speed * 60)
        self.color = (brightness, brightness, min(255, brightness + 30))

    def update(self, dt=1/60):
        self.y += self.speed
        if self.y > self.height:
            self.y = 0
            self.x = random.randint(0, self.width)

    def draw(self, surface):
        if surface is None:
            return
        if self.size == 1:
            try:
                surface.set_at((int(self.x), int(self.y)), self.color)
            except Exception:
                pass
        else:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), self.size)


class Particle(pygame.sprite.Sprite):
    """Explosion / thruster particle effect."""
    def __init__(self, x, y, vx=None, vy=None, color=ORANGE, radius=3, lifetime=25):
        super().__init__()
        if vx is None or vy is None:
            angle = random.uniform(0, math.pi * 2)
            spd = random.uniform(1.0, 4.0)
            self.vx = math.cos(angle) * spd
            self.vy = math.sin(angle) * spd
        else:
            self.vx = float(vx)
            self.vy = float(vy)

        self.x = float(x)
        self.y = float(y)
        self.color = color
        self.original_radius = radius
        self.radius = radius
        self.lifetime = lifetime
        self.max_lifetime = max(1, lifetime)

        self.image = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(self.image, color, (radius, radius), radius)
        self.rect = self.image.get_rect(center=(int(x), int(y)))

    def update(self, dt=1/60):
        self.lifetime -= 1
        if self.lifetime <= 0:
            self.kill()
            return

        self.x += self.vx
        self.y += self.vy
        ratio = max(0.0, self.lifetime / self.max_lifetime)
        alpha = int(255 * ratio)
        r = max(1, int(self.original_radius * ratio))

        self.image = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        col = (*self.color[:3], max(0, min(255, alpha)))
        pygame.draw.circle(self.image, col, (r, r), r)
        self.rect = self.image.get_rect(center=(int(self.x), int(self.y)))


class Laser(pygame.sprite.Sprite):
    """Laser projectile fired by the player or enemies."""
    def __init__(self, x, y, speed_y=-10, speed_x=0, damage=15, is_player=True, color=CYAN, width=4, height=14):
        super().__init__()
        self.is_player = is_player
        self.damage = damage
        self.speed_x = float(speed_x)
        self.speed_y = float(speed_y)
        self.width = width
        self.height = height
        self.color = color
        self.image = create_laser_surface(width, height, color)
        self.rect = self.image.get_rect(center=(int(x), int(y)))
        self.exact_x = float(self.rect.centerx)
        self.exact_y = float(self.rect.centery)

    def update(self, dt=1/60):
        self.exact_x += self.speed_x
        self.exact_y += self.speed_y
        self.rect.centerx = int(self.exact_x)
        self.rect.centery = int(self.exact_y)

        if self.is_off_screen():
            self.kill()

    def is_off_screen(self, screen_width=SCREEN_WIDTH, screen_height=SCREEN_HEIGHT):
        return (self.rect.bottom < 0 or
                self.rect.top > screen_height or
                self.rect.right < 0 or
                self.rect.left > screen_width)


class PowerUp(pygame.sprite.Sprite):
    """Collectable power-up capsule dropping from defeated enemies."""
    def __init__(self, x, y, power_type=PowerUpType.HEALTH, speed_y=2.0, size=24):
        super().__init__()
        self.power_type = power_type
        self.speed_y = float(speed_y)
        self.size = size
        self.image = create_powerup_surface(size, size, power_type)
        self.rect = self.image.get_rect(center=(int(x), int(y)))
        self.exact_y = float(self.rect.centery)

    def update(self, dt=1/60, screen_height=SCREEN_HEIGHT):
        self.exact_y += self.speed_y
        self.rect.centery = int(self.exact_y)
        if self.rect.top > screen_height:
            self.kill()

    def apply(self, player, game=None):
        if self.power_type == PowerUpType.HEALTH:
            if player.health >= player.max_health:
                player.add_score(500)
            else:
                player.heal(30)
        elif self.power_type == PowerUpType.SHIELD:
            player.activate_shield(amount=100, duration=10.0)
        elif self.power_type == PowerUpType.DOUBLE_SHOT:
            player.upgrade_weapon(level=2, duration=15.0)
        elif self.power_type == PowerUpType.TRIPLE_SHOT:
            player.upgrade_weapon(level=3, duration=15.0)
        elif self.power_type == PowerUpType.SPEED_BOOST:
            player.activate_speed_boost(multiplier=1.5, duration=10.0)
        elif self.power_type == PowerUpType.BOMB:
            if game is not None:
                game.trigger_bomb()
            else:
                player.add_score(200)
        self.kill()


class Enemy(pygame.sprite.Sprite):
    """Alien enemy spacecraft with varying behaviors and firing patterns."""
    def __init__(self, x, y, enemy_type=EnemyType.SCOUT, level=1):
        super().__init__()
        self.enemy_type = enemy_type
        self.level = level
        self.alive = True

        if enemy_type == EnemyType.SCOUT:
            self.width = 32
            self.height = 32
            self.speed_x = 0.0
            self.speed_y = 3.2
            self.health = 20
            self.max_health = 20
            self.points = 100
            self.can_shoot = False
            self.color = RED
        elif enemy_type == EnemyType.FIGHTER:
            self.width = 38
            self.height = 38
            self.speed_x = 1.8
            self.speed_y = 2.0
            self.health = 40
            self.max_health = 40
            self.points = 200
            self.can_shoot = True
            self.shoot_interval = 1400
            self.bullet_damage = 10
            self.color = PURPLE
        elif enemy_type == EnemyType.BOMBER:
            self.width = 48
            self.height = 48
            self.speed_x = 0.0
            self.speed_y = 1.2
            self.health = 80
            self.max_health = 80
            self.points = 350
            self.can_shoot = True
            self.shoot_interval = 2000
            self.bullet_damage = 20
            self.color = ORANGE
        elif enemy_type == EnemyType.BOSS:
            self.width = 110
            self.height = 70
            self.speed_x = 2.0
            self.speed_y = 1.0
            self.health = 350 + level * 100
            self.max_health = self.health
            self.points = 2000
            self.can_shoot = True
            self.shoot_interval = 900
            self.bullet_damage = 15
            self.color = YELLOW
            self.target_y = 80
        else:
            self.width = 32
            self.height = 32
            self.speed_x = 0.0
            self.speed_y = 3.0
            self.health = 20
            self.max_health = 20
            self.points = 100
            self.can_shoot = False
            self.color = RED

        self.last_shot_time = -random.randint(0, 400)
        self.image = create_enemy_surface(self.width, self.height, self.enemy_type, self.color)
        self.rect = self.image.get_rect(center=(int(x), int(y)))
        self.exact_x = float(self.rect.centerx)
        self.exact_y = float(self.rect.centery)
        self.sine_offset = random.random() * math.pi * 2

    def update(self, dt=1/60, screen_width=SCREEN_WIDTH, screen_height=SCREEN_HEIGHT):
        if self.enemy_type == EnemyType.BOSS:
            if self.exact_y < getattr(self, 'target_y', 80):
                self.exact_y += self.speed_y
            else:
                self.exact_x += self.speed_x
                if self.rect.right >= screen_width - 15:
                    self.speed_x = -abs(self.speed_x)
                elif self.rect.left <= 15:
                    self.speed_x = abs(self.speed_x)
        elif self.enemy_type == EnemyType.FIGHTER:
            self.exact_y += self.speed_y
            self.exact_x += self.speed_x
            if self.rect.right >= screen_width or self.rect.left <= 0:
                self.speed_x = -self.speed_x
        elif self.enemy_type == EnemyType.SCOUT:
            self.exact_y += self.speed_y
            self.exact_x += math.sin(self.exact_y * 0.03 + self.sine_offset) * 1.5
        else:
            self.exact_y += self.speed_y
            self.exact_x += self.speed_x

        self.rect.centerx = int(self.exact_x)
        self.rect.centery = int(self.exact_y)

        if self.is_off_screen(screen_width, screen_height):
            self.alive = False
            self.kill()

    def is_off_screen(self, screen_width=SCREEN_WIDTH, screen_height=SCREEN_HEIGHT):
        return self.rect.top > screen_height

    def take_damage(self, amount):
        if not self.alive or amount <= 0:
            return False
        self.health -= amount
        if self.health <= 0:
            self.health = 0
            self.alive = False
            return True
        return False

    def shoot(self, current_time=None):
        if not self.can_shoot or not self.alive:
            return []
        if current_time is None:
            try:
                current_time = pygame.time.get_ticks()
            except Exception:
                current_time = 0

        interval = getattr(self, 'shoot_interval', 1500)
        if current_time - self.last_shot_time < interval:
            return []

        self.last_shot_time = current_time
        lasers = []
        cx = self.rect.centerx
        bot_y = self.rect.bottom

        if self.enemy_type == EnemyType.BOSS:
            lasers.append(Laser(cx, bot_y, speed_y=5.0, speed_x=0.0, damage=self.bullet_damage, is_player=False, color=YELLOW, width=6, height=16))
            lasers.append(Laser(cx - 25, bot_y - 8, speed_y=4.5, speed_x=-1.8, damage=self.bullet_damage, is_player=False, color=ORANGE, width=5, height=14))
            lasers.append(Laser(cx + 25, bot_y - 8, speed_y=4.5, speed_x=1.8, damage=self.bullet_damage, is_player=False, color=ORANGE, width=5, height=14))
        elif self.enemy_type == EnemyType.BOMBER:
            lasers.append(Laser(cx, bot_y, speed_y=4.5, speed_x=0.0, damage=self.bullet_damage, is_player=False, color=ORANGE, width=6, height=16))
        else:
            lasers.append(Laser(cx, bot_y, speed_y=5.0, speed_x=0.0, damage=self.bullet_damage, is_player=False, color=RED, width=4, height=12))

        return lasers


class Player(pygame.sprite.Sprite):
    """Player spaceship entity controlled by the user."""
    def __init__(self, x=SCREEN_WIDTH // 2, y=SCREEN_HEIGHT - 60):
        super().__init__()
        self.width = 40
        self.height = 40
        self.image = create_player_surface(self.width, self.height)
        self.rect = self.image.get_rect(center=(int(x), int(y)))

        self.base_speed = 5.0
        self.speed = 5.0
        self.speed_boost_timer = 0.0

        self.max_health = 100
        self.health = 100
        self.max_shield = 100
        self.shield = 0
        self.shield_timer = 0.0

        self.lives = 3
        self.score = 0
        self.weapon_level = 1
        self.weapon_timer = 0.0

        self.shoot_delay = 200  # milliseconds
        self.last_shot_time = -10000

        self.invulnerable = False
        self.invulnerable_timer = 0.0
        self.invulnerable_duration = 2000.0
        self.alive = True

    def move(self, dx, dy, bounds=(SCREEN_WIDTH, SCREEN_HEIGHT)):
        self.rect.x += int(dx)
        self.rect.y += int(dy)
        self.clamp_position(bounds)

    def move_left(self):
        self.move(-self.speed, 0)

    def move_right(self):
        self.move(self.speed, 0)

    def move_up(self):
        self.move(0, -self.speed)

    def move_down(self):
        self.move(0, self.speed)

    def clamp_position(self, bounds=(SCREEN_WIDTH, SCREEN_HEIGHT)):
        max_w, max_h = bounds
        if self.rect.left < 0:
            self.rect.left = 0
        if self.rect.right > max_w:
            self.rect.right = max_w
        if self.rect.top < 0:
            self.rect.top = 0
        if self.rect.bottom > max_h:
            self.rect.bottom = max_h

    def shoot(self, current_time=None):
        if not self.alive:
            return []
        if current_time is None:
            try:
                current_time = pygame.time.get_ticks()
            except Exception:
                current_time = 0

        if current_time - self.last_shot_time < self.shoot_delay:
            return []

        self.last_shot_time = current_time
        lasers = []
        cx = self.rect.centerx
        top_y = self.rect.top

        if self.weapon_level == 1:
            lasers.append(Laser(cx, top_y, speed_y=-10.0, speed_x=0.0, damage=15, is_player=True, color=CYAN))
        elif self.weapon_level == 2:
            lasers.append(Laser(cx - 14, top_y + 4, speed_y=-10.0, speed_x=0.0, damage=15, is_player=True, color=CYAN))
            lasers.append(Laser(cx + 14, top_y + 4, speed_y=-10.0, speed_x=0.0, damage=15, is_player=True, color=CYAN))
        else:
            lasers.append(Laser(cx, top_y, speed_y=-11.0, speed_x=0.0, damage=15, is_player=True, color=CYAN))
            lasers.append(Laser(cx - 16, top_y + 4, speed_y=-10.0, speed_x=-2.5, damage=12, is_player=True, color=LIGHT_BLUE))
            lasers.append(Laser(cx + 16, top_y + 4, speed_y=-10.0, speed_x=2.5, damage=12, is_player=True, color=LIGHT_BLUE))

        return lasers

    def take_damage(self, amount):
        if not self.alive or self.invulnerable or amount <= 0:
            return 0

        damage_dealt = 0
        if self.shield > 0:
            if self.shield >= amount:
                self.shield -= amount
                return amount
            else:
                absorbed = self.shield
                self.shield = 0
                damage_dealt += absorbed
                amount -= absorbed

        self.health -= amount
        damage_dealt += amount

        if self.health <= 0:
            self.lives -= 1
            if self.lives > 0:
                self.health = self.max_health
                self.invulnerable = True
                self.invulnerable_timer = self.invulnerable_duration
            else:
                self.health = 0
                self.alive = False
        else:
            self.invulnerable = True
            self.invulnerable_timer = 500.0

        return damage_dealt

    def heal(self, amount):
        if not self.alive or amount <= 0:
            return 0
        old_health = self.health
        self.health = min(self.max_health, self.health + amount)
        return self.health - old_health

    def activate_shield(self, amount=100, duration=10.0):
        self.shield = min(self.max_shield, self.shield + amount)
        self.shield_timer = duration * 1000.0

    def upgrade_weapon(self, level=None, duration=15.0):
        if level is None:
            self.weapon_level = min(3, self.weapon_level + 1)
        else:
            self.weapon_level = max(self.weapon_level, level)
        self.weapon_timer = duration * 1000.0

    def activate_speed_boost(self, multiplier=1.5, duration=10.0):
        self.speed = self.base_speed * multiplier
        self.speed_boost_timer = duration * 1000.0

    def add_score(self, points):
        self.score += points

    def update(self, dt=1/60):
        ms = dt * 1000.0
        if self.invulnerable_timer > 0:
            self.invulnerable_timer -= ms
            if self.invulnerable_timer <= 0:
                self.invulnerable = False

        if self.shield_timer > 0:
            self.shield_timer -= ms
            if self.shield_timer <= 0:
                self.shield = 0

        if self.weapon_timer > 0:
            self.weapon_timer -= ms
            if self.weapon_timer <= 0:
                self.weapon_level = 1

        if self.speed_boost_timer > 0:
            self.speed_boost_timer -= ms
            if self.speed_boost_timer <= 0:
                self.speed = self.base_speed

    def reset(self, full=True):
        self.rect.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60)
        self.health = self.max_health
        self.shield = 0
        self.shield_timer = 0.0
        self.weapon_level = 1
        self.weapon_timer = 0.0
        self.speed = self.base_speed
        self.speed_boost_timer = 0.0
        self.invulnerable = False
        self.invulnerable_timer = 0.0
        self.alive = True
        if full:
            self.lives = 3
            self.score = 0


class SpaceShooterGame:
    """Core Game engine orchestrating entities, collisions, states, and rendering."""
    def __init__(self, width=SCREEN_WIDTH, height=SCREEN_HEIGHT, sound_enabled=False):
        init_pygame()
        self.width = width
        self.height = height
        self.sound_enabled = sound_enabled

        self.state = GameState.MENU
        self.player = Player(width // 2, height - 60)

        self.all_sprites = pygame.sprite.Group()
        self.enemies = pygame.sprite.Group()
        self.player_lasers = pygame.sprite.Group()
        self.enemy_lasers = pygame.sprite.Group()
        self.powerups = pygame.sprite.Group()
        self.particles = pygame.sprite.Group()

        self.all_sprites.add(self.player)
        self.stars = [Star(width=width, height=height) for _ in range(60)]

        self.score = 0
        self.high_score = 0
        self.wave = 1
        self.enemies_killed = 0
        self.spawn_delay = 1200
        self.last_spawn_time = 0
        self.boss_active = False
        self.current_boss = None

        self.running = True
        self.screen = None

    def start_game(self):
        self.state = GameState.PLAYING
        self.reset()

    def pause_game(self):
        if self.state == GameState.PLAYING:
            self.state = GameState.PAUSED
        elif self.state == GameState.PAUSED:
            self.state = GameState.PLAYING

    def game_over(self):
        self.state = GameState.GAME_OVER
        if self.player.score > self.high_score:
            self.high_score = self.player.score

    def reset(self):
        self.player.reset(full=True)
        self.enemies.empty()
        self.player_lasers.empty()
        self.enemy_lasers.empty()
        self.powerups.empty()
        self.particles.empty()
        self.all_sprites.empty()
        self.all_sprites.add(self.player)
        self.wave = 1
        self.enemies_killed = 0
        self.boss_active = False
        self.current_boss = None
        self.last_spawn_time = 0

    def spawn_enemy(self, enemy_type=None, x=None, y=None):
        if enemy_type is None:
            enemy_type = random.choice([EnemyType.SCOUT, EnemyType.FIGHTER])
        if x is None:
            margin = 50
            x = random.randint(margin, max(margin + 1, self.width - margin))
        if y is None:
            y = -30
        enemy = Enemy(x, y, enemy_type=enemy_type, level=self.wave)
        self.enemies.add(enemy)
        self.all_sprites.add(enemy)
        return enemy

    def spawn_boss(self):
        self.boss_active = True
        boss = Enemy(self.width // 2, -40, enemy_type=EnemyType.BOSS, level=self.wave)
        self.current_boss = boss
        self.enemies.add(boss)
        self.all_sprites.add(boss)
        return boss

    def spawn_powerup(self, x, y, power_type=None):
        if power_type is None:
            power_type = random.choice(PowerUpType.ALL_TYPES)
        powerup = PowerUp(x, y, power_type=power_type)
        self.powerups.add(powerup)
        self.all_sprites.add(powerup)
        return powerup

    def spawn_explosion(self, x, y, count=15, color=ORANGE):
        for _ in range(count):
            p = Particle(x, y, color=color)
            self.particles.add(p)
            self.all_sprites.add(p)

    def trigger_bomb(self):
        score_gained = 0
        for enemy in list(self.enemies):
            if enemy.enemy_type == EnemyType.BOSS:
                killed = enemy.take_damage(150)
            else:
                killed = enemy.take_damage(999)
            self.spawn_explosion(enemy.rect.centerx, enemy.rect.centery, count=16, color=enemy.color)
            if killed:
                self.player.add_score(enemy.points)
                score_gained += enemy.points
                self.enemies_killed += 1
                if enemy.enemy_type == EnemyType.BOSS:
                    self.boss_active = False
                    self.current_boss = None
                    self.wave += 1
                enemy.kill()

        for laser in list(self.enemy_lasers):
            laser.kill()

        return score_gained

    def player_shoot(self, current_time=None):
        if self.state != GameState.PLAYING or not self.player.alive:
            return []
        lasers = self.player.shoot(current_time=current_time)
        for laser in lasers:
            self.player_lasers.add(laser)
            self.all_sprites.add(laser)
        return lasers

    def check_spawns(self, current_time=None):
        if current_time is None:
            try:
                current_time = pygame.time.get_ticks()
            except Exception:
                current_time = 0

        # Spawn boss if kill threshold met
        if not self.boss_active and self.enemies_killed >= self.wave * 10:
            self.spawn_boss()
            return

        delay = self.spawn_delay * 2 if self.boss_active else self.spawn_delay
        if current_time - self.last_spawn_time >= delay:
            self.last_spawn_time = current_time
            types = [EnemyType.SCOUT]
            if self.wave >= 2:
                types.append(EnemyType.FIGHTER)
            if self.wave >= 3:
                types.append(EnemyType.BOMBER)
            chosen_type = random.choice(types)
            self.spawn_enemy(chosen_type)

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return True

        if event.type == pygame.KEYDOWN:
            if self.state == GameState.MENU:
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.start_game()
            elif self.state == GameState.PLAYING:
                if event.key in (pygame.K_p, pygame.K_ESCAPE):
                    self.pause_game()
                elif event.key == pygame.K_SPACE:
                    self.player_shoot()
            elif self.state == GameState.PAUSED:
                if event.key in (pygame.K_p, pygame.K_ESCAPE):
                    self.pause_game()
            elif self.state == GameState.GAME_OVER:
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.start_game()
                elif event.key == pygame.K_m:
                    self.state = GameState.MENU
        return False

    def handle_input(self, keys_pressed, current_time=None):
        if self.state != GameState.PLAYING or not self.player.alive or keys_pressed is None:
            return

        if keys_pressed[pygame.K_LEFT] or keys_pressed[pygame.K_a]:
            self.player.move_left()
        if keys_pressed[pygame.K_RIGHT] or keys_pressed[pygame.K_d]:
            self.player.move_right()
        if keys_pressed[pygame.K_UP] or keys_pressed[pygame.K_w]:
            self.player.move_up()
        if keys_pressed[pygame.K_DOWN] or keys_pressed[pygame.K_s]:
            self.player.move_down()

        if keys_pressed[pygame.K_SPACE]:
            self.player_shoot(current_time=current_time)

    def update(self, dt=1/60, current_time=None):
        if current_time is None:
            try:
                current_time = pygame.time.get_ticks()
            except Exception:
                current_time = 0

        for star in self.stars:
            star.update(dt=dt)
        self.particles.update(dt=dt)

        if self.state != GameState.PLAYING:
            return

        self.player.update(dt=dt)
        if not self.player.alive:
            self.game_over()
            return

        self.player_lasers.update(dt=dt)

        for enemy in list(self.enemies):
            enemy.update(dt=dt, screen_width=self.width, screen_height=self.height)
            if enemy.can_shoot and enemy.alive:
                e_lasers = enemy.shoot(current_time=current_time)
                for laser in e_lasers:
                    self.enemy_lasers.add(laser)
                    self.all_sprites.add(laser)

        self.enemy_lasers.update(dt=dt)

        for p in list(self.powerups):
            p.update(dt=dt, screen_height=self.height)

        self.check_spawns(current_time=current_time)

        # 1. Player lasers vs Enemies
        hits = pygame.sprite.groupcollide(self.enemies, self.player_lasers, False, True)
        for enemy, laser_list in hits.items():
            for laser in laser_list:
                killed = enemy.take_damage(laser.damage)
                self.spawn_explosion(laser.rect.centerx, laser.rect.centery, count=4, color=CYAN)
                if killed:
                    self.spawn_explosion(enemy.rect.centerx, enemy.rect.centery, count=16, color=enemy.color)
                    self.player.add_score(enemy.points)
                    self.enemies_killed += 1
                    if random.random() < 0.25:
                        self.spawn_powerup(enemy.rect.centerx, enemy.rect.centery)
                    if enemy.enemy_type == EnemyType.BOSS:
                        self.boss_active = False
                        self.current_boss = None
                        self.wave += 1
                        self.player.heal(50)
                        self.spawn_powerup(enemy.rect.centerx, enemy.rect.centery, PowerUpType.TRIPLE_SHOT)
                    enemy.kill()
                    break

        # 2. Enemy lasers vs Player
        if self.player.alive:
            e_hits = pygame.sprite.spritecollide(self.player, self.enemy_lasers, True)
            for laser in e_hits:
                self.player.take_damage(laser.damage)
                self.spawn_explosion(laser.rect.centerx, laser.rect.centery, count=6, color=laser.color)
                if not self.player.alive:
                    self.spawn_explosion(self.player.rect.centerx, self.player.rect.centery, count=30, color=RED)
                    self.game_over()
                    break

        # 3. Enemies vs Player
        if self.player.alive:
            ship_hits = pygame.sprite.spritecollide(self.player, self.enemies, False)
            for enemy in ship_hits:
                e_killed = enemy.take_damage(50)
                self.player.take_damage(30)
                self.spawn_explosion(self.player.rect.centerx, self.player.rect.centery, count=10, color=ORANGE)
                if e_killed:
                    self.spawn_explosion(enemy.rect.centerx, enemy.rect.centery, count=16, color=enemy.color)
                    self.player.add_score(enemy.points)
                    self.enemies_killed += 1
                    enemy.kill()
                if not self.player.alive:
                    self.spawn_explosion(self.player.rect.centerx, self.player.rect.centery, count=30, color=RED)
                    self.game_over()
                    break

        # 4. Player vs Powerups
        if self.player.alive:
            p_hits = pygame.sprite.spritecollide(self.player, self.powerups, False)
            for p in p_hits:
                p.apply(self.player, game=self)
                self.spawn_explosion(p.rect.centerx, p.rect.centery, count=10, color=GREEN)

    def step(self, dt=1/60, keys_pressed=None, current_time=None):
        """Executes a single discrete frame step."""
        if keys_pressed is not None:
            self.handle_input(keys_pressed, current_time=current_time)
        self.update(dt=dt, current_time=current_time)

    def draw(self, surface):
        if surface is None:
            return

        # Background
        surface.fill(BLACK)
        for star in self.stars:
            star.draw(surface)

        self.particles.draw(surface)
        self.powerups.draw(surface)

        # Enemies & their health bars
        self.enemies.draw(surface)
        for enemy in self.enemies:
            if enemy.health < enemy.max_health or enemy.enemy_type == EnemyType.BOSS:
                bar_w = enemy.rect.width
                bar_h = 4
                bar_x = enemy.rect.left
                bar_y = enemy.rect.top - 6
                fill_w = max(0, int(bar_w * (enemy.health / enemy.max_health)))
                pygame.draw.rect(surface, DARK_GRAY, (bar_x, bar_y, bar_w, bar_h))
                pygame.draw.rect(surface, GREEN if enemy.health > enemy.max_health * 0.4 else RED, (bar_x, bar_y, fill_w, bar_h))

        # Player
        if self.player.alive:
            show_player = True
            if self.player.invulnerable:
                try:
                    show_player = (pygame.time.get_ticks() // 100) % 2 == 0
                except Exception:
                    show_player = True
            if show_player:
                surface.blit(self.player.image, self.player.rect)

            if self.player.shield > 0:
                pygame.draw.ellipse(surface, CYAN, self.player.rect.inflate(14, 14), 2)

        self.player_lasers.draw(surface)
        self.enemy_lasers.draw(surface)

        # HUD
        font_sm = get_font(22)
        font_md = get_font(32)
        font_lg = get_font(52)

        # Score & High Score
        render_text(surface, f"SCORE: {self.player.score}", font_sm, WHITE, top_left=(14, 12))
        render_text(surface, f"HIGH: {self.high_score}", font_sm, YELLOW, center_pos=(self.width // 2, 22))
        render_text(surface, f"WAVE: {self.wave}", font_sm, CYAN, top_left=(self.width - 120, 12))

        # Health & Shield Bars
        bar_w = 140
        bar_h = 12
        pygame.draw.rect(surface, DARK_GRAY, (14, 38, bar_w, bar_h))
        fill_hp = max(0, int(bar_w * (self.player.health / self.player.max_health)))
        hp_color = GREEN if self.player.health > 50 else (YELLOW if self.player.health > 25 else RED)
        pygame.draw.rect(surface, hp_color, (14, 38, fill_hp, bar_h))
        pygame.draw.rect(surface, WHITE, (14, 38, bar_w, bar_h), 1)

        if self.player.shield > 0:
            fill_shield = max(0, int(bar_w * (self.player.shield / self.player.max_shield)))
            pygame.draw.rect(surface, CYAN, (14, 53, fill_shield, 6))
            pygame.draw.rect(surface, WHITE, (14, 53, bar_w, 6), 1)

        # Lives
        render_text(surface, f"LIVES: {self.player.lives}", font_sm, WHITE, top_left=(14, 65))
        if self.player.weapon_level > 1:
            render_text(surface, f"WEAPON LVL {self.player.weapon_level}", font_sm, ORANGE, top_left=(14, 85))

        # State Overlays
        if self.state == GameState.MENU:
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))
            render_text(surface, "SPACE SHOOTER", font_lg, CYAN, center_pos=(self.width // 2, self.height // 2 - 80))
            render_text(surface, "Press SPACE or ENTER to Start", font_md, YELLOW, center_pos=(self.width // 2, self.height // 2))
            render_text(surface, "Controls: Arrow Keys / WASD to Move, SPACE to Shoot", font_sm, WHITE, center_pos=(self.width // 2, self.height // 2 + 60))
            render_text(surface, "P to Pause", font_sm, GRAY, center_pos=(self.width // 2, self.height // 2 + 90))

        elif self.state == GameState.PAUSED:
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            surface.blit(overlay, (0, 0))
            render_text(surface, "PAUSED", font_lg, YELLOW, center_pos=(self.width // 2, self.height // 2 - 40))
            render_text(surface, "Press P or ESC to Resume", font_md, WHITE, center_pos=(self.width // 2, self.height // 2 + 30))

        elif self.state == GameState.GAME_OVER:
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 190))
            surface.blit(overlay, (0, 0))
            render_text(surface, "GAME OVER", font_lg, RED, center_pos=(self.width // 2, self.height // 2 - 80))
            render_text(surface, f"Final Score: {self.player.score}", font_md, WHITE, center_pos=(self.width // 2, self.height // 2 - 20))
            render_text(surface, f"High Score: {self.high_score}", font_sm, YELLOW, center_pos=(self.width // 2, self.height // 2 + 20))
            render_text(surface, "Press SPACE or ENTER to Restart", font_md, GREEN, center_pos=(self.width // 2, self.height // 2 + 70))
            render_text(surface, "Press M for Menu", font_sm, GRAY, center_pos=(self.width // 2, self.height // 2 + 110))

    def run(self, max_frames=None):
        """Runs the main game loop."""
        if self.screen is None:
            self.screen = create_screen(self.width, self.height)

        clock = pygame.time.Clock()
        frames = 0

        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)

            keys = pygame.key.get_pressed()
            self.step(dt=1/FPS, keys_pressed=keys)

            self.draw(self.screen)
            pygame.display.flip()
            clock.tick(FPS)

            frames += 1
            if max_frames is not None and frames >= max_frames:
                break


# Alias for clean accessibility
Game = SpaceShooterGame


def main():
    game = SpaceShooterGame()
    game.run()


if __name__ == "__main__":
    main()
