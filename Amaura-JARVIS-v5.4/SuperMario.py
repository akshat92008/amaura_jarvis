"""
SuperMario.py - Complete, fully playable 2D platformer Mario game in Python using Pygame.

Features:
- Responsive Mario jumping physics with gravity, acceleration, deceleration, and variable jump height
- Platforms: Ground, floating bricks, bumpable mystery/question blocks, and pipes
- Collectible coins placed in the level and hidden inside question blocks
- Patrol enemies (Goombas) that can be defeated by jumping/stomping on them
- Score, coin counter, remaining time, and lives HUD
- Death boundaries (falling into pits resets position or triggers game over)
- Flagpole goal with victory sequence and castle
- Dynamic scrolling camera
- Procedural pixel-art visuals and synthesized audio effects (with headless/fallback support)
"""

import os
import sys
import math
import wave
import struct
import io
import pygame

# Initialize pygame display and audio safely (handles headless testing environments)
def safe_init():
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()

    # Try setting a display mode or fall back to dummy video driver if headless
    if not pygame.display.get_init():
        try:
            pygame.display.init()
        except pygame.error:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            pygame.display.init()

    # Audio initialization with fallback
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
    except Exception:
        pass

safe_init()

# --- CONSTANTS ---
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Palette
COLOR_SKY = (107, 140, 255)
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GROUND_DIRT = (180, 82, 22)
COLOR_GROUND_GRASS = (34, 177, 76)
COLOR_BRICK = (196, 70, 20)
COLOR_BRICK_DARK = (128, 40, 10)
COLOR_QUESTION_BLOCK = (252, 178, 38)
COLOR_QUESTION_HIT = (146, 114, 88)
COLOR_PIPE_GREEN = (0, 168, 0)
COLOR_PIPE_LIGHT = (76, 220, 76)
COLOR_PIPE_DARK = (0, 100, 0)
COLOR_COIN_GOLD = (255, 215, 0)
COLOR_COIN_LIGHT = (255, 245, 140)
COLOR_COIN_DARK = (200, 150, 0)
COLOR_GOOMBA_BROWN = (144, 60, 20)
COLOR_GOOMBA_DARK = (80, 30, 10)
COLOR_MARIO_RED = (230, 35, 35)
COLOR_MARIO_BLUE = (15, 60, 210)
COLOR_MARIO_SKIN = (255, 205, 155)
COLOR_MARIO_BROWN = (100, 45, 15)

# Physics constants
GRAVITY = 0.75
MAX_FALL_SPEED = 13.0
WALK_ACCEL = 0.35
MAX_WALK_SPEED = 4.2
RUN_ACCEL = 0.55
MAX_RUN_SPEED = 6.8
FRICTION = 0.22
JUMP_FORCE = -13.8
BOUNCE_FORCE = -9.2
DEATH_Y = 620


# --- SYNTHESIZED SOUND MANAGER ---
class SoundManager:
    """Generates simple procedural 8-bit sound effects without external audio files."""
    def __init__(self):
        self.enabled = pygame.mixer.get_init() is not None
        self.sounds = {}
        if self.enabled:
            self._generate_sounds()

    def _generate_sine_wav(self, freqs, durations, volume=0.4):
        """Builds an in-memory WAV file from frequency/duration pairs."""
        sample_rate = 22050
        samples = []
        for freq, dur in zip(freqs, durations):
            num_samples = int(sample_rate * dur)
            for i in range(num_samples):
                t = float(i) / sample_rate
                # Apply simple envelope to avoid clicks
                envelope = 1.0 - (i / num_samples)
                if freq == 0:
                    val = 0
                else:
                    val = math.sin(2.0 * math.pi * freq * t)
                sample = int(val * envelope * volume * 32767)
                samples.append(sample)

        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            raw_data = struct.pack(f'<{len(samples)}h', *samples)
            wav.writeframes(raw_data)
        buffer.seek(0)
        return pygame.mixer.Sound(buffer)

    def _generate_sounds(self):
        try:
            # Jump sound: rising pitch
            self.sounds['jump'] = self._generate_sine_wav([200, 320, 480], [0.05, 0.05, 0.08])
            # Coin sound: high two-tone ding
            self.sounds['coin'] = self._generate_sine_wav([988, 1318], [0.08, 0.22])
            # Stomp sound: low thud
            self.sounds['stomp'] = self._generate_sine_wav([220, 110], [0.06, 0.08])
            # Bump sound: low blunt hit
            self.sounds['bump'] = self._generate_sine_wav([150, 90], [0.04, 0.06])
            # Die sound: falling sad sequence
            self.sounds['die'] = self._generate_sine_wav([440, 415, 392, 330], [0.12, 0.12, 0.12, 0.3])
            # Stage clear fanfare
            self.sounds['win'] = self._generate_sine_wav([392, 523, 659, 784], [0.1, 0.1, 0.1, 0.4])
        except Exception:
            self.enabled = False

    def play(self, name):
        if self.enabled and name in self.sounds:
            try:
                self.sounds[name].play()
            except Exception:
                pass


# Global sound manager instance
sound_manager = SoundManager()


# --- SPRITE GENERATION HELPERS ---
def create_mario_surface(state='idle', facing_right=True):
    surf = pygame.Surface((30, 40), pygame.SRCALPHA)
    # Hat
    pygame.draw.rect(surf, COLOR_MARIO_RED, (6, 2, 18, 6))
    pygame.draw.rect(surf, COLOR_MARIO_RED, (10, 8, 16, 4))
    # Face & Nose
    pygame.draw.rect(surf, COLOR_MARIO_SKIN, (8, 10, 14, 10))
    pygame.draw.rect(surf, COLOR_MARIO_SKIN, (18, 12, 6, 6))
    # Mustache & Hair
    pygame.draw.rect(surf, COLOR_MARIO_BROWN, (4, 8, 6, 8))
    pygame.draw.rect(surf, COLOR_MARIO_BROWN, (14, 16, 12, 4))
    # Eye
    pygame.draw.rect(surf, COLOR_BLACK, (14, 11, 2, 4))
    # Red Shirt
    pygame.draw.rect(surf, COLOR_MARIO_RED, (6, 20, 18, 10))
    # Blue Overalls
    pygame.draw.rect(surf, COLOR_MARIO_BLUE, (8, 24, 14, 10))
    pygame.draw.rect(surf, COLOR_MARIO_BLUE, (8, 22, 4, 4))
    pygame.draw.rect(surf, COLOR_MARIO_BLUE, (18, 22, 4, 4))
    # Yellow buttons
    pygame.draw.rect(surf, (255, 230, 0), (9, 25, 2, 2))
    pygame.draw.rect(surf, (255, 230, 0), (19, 25, 2, 2))

    if state == 'jump':
        # Arms up / legs extended
        pygame.draw.rect(surf, COLOR_MARIO_RED, (22, 14, 6, 8))
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (4, 32, 10, 5))
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (16, 30, 10, 6))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (2, 36, 10, 4))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (18, 34, 10, 5))
    elif state == 'walk_2':
        # Walking frame 2
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (4, 32, 8, 6))
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (18, 32, 8, 6))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (2, 36, 8, 4))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (20, 36, 8, 4))
    else:
        # Idle / Walk frame 1
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (6, 32, 8, 6))
        pygame.draw.rect(surf, COLOR_MARIO_BLUE, (16, 32, 8, 6))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (4, 36, 10, 4))
        pygame.draw.rect(surf, COLOR_MARIO_BROWN, (16, 36, 10, 4))

    if not facing_right:
        surf = pygame.transform.flip(surf, True, False)
    return surf


def create_goomba_surface(squished=False):
    if squished:
        surf = pygame.Surface((32, 14), pygame.SRCALPHA)
        pygame.draw.ellipse(surf, COLOR_GOOMBA_BROWN, (0, 2, 32, 12))
        pygame.draw.rect(surf, COLOR_GOOMBA_DARK, (2, 10, 28, 4))
        return surf

    surf = pygame.Surface((32, 32), pygame.SRCALPHA)
    # Head / cap (mushroom shape)
    pygame.draw.ellipse(surf, COLOR_GOOMBA_BROWN, (2, 2, 28, 22))
    # Face
    pygame.draw.rect(surf, (220, 170, 130), (8, 14, 16, 12))
    # Eyebrows
    pygame.draw.line(surf, COLOR_BLACK, (8, 13), (13, 16), 2)
    pygame.draw.line(surf, COLOR_BLACK, (23, 13), (18, 16), 2)
    # Eyes
    pygame.draw.rect(surf, COLOR_WHITE, (9, 16, 4, 6))
    pygame.draw.rect(surf, COLOR_BLACK, (11, 17, 2, 5))
    pygame.draw.rect(surf, COLOR_WHITE, (19, 16, 4, 6))
    pygame.draw.rect(surf, COLOR_BLACK, (19, 17, 2, 5))
    # Feet
    pygame.draw.ellipse(surf, COLOR_GOOMBA_DARK, (2, 24, 12, 8))
    pygame.draw.ellipse(surf, COLOR_GOOMBA_DARK, (18, 24, 12, 8))
    return surf


def create_coin_surface(frame=0):
    widths = [18, 12, 6, 12]
    w = widths[frame % 4]
    surf = pygame.Surface((20, 24), pygame.SRCALPHA)
    x_offset = (20 - w) // 2
    pygame.draw.ellipse(surf, COLOR_COIN_GOLD, (x_offset, 2, w, 20))
    pygame.draw.ellipse(surf, COLOR_COIN_LIGHT, (x_offset + 1, 4, max(1, w - 2), 16), 1)
    if w >= 10:
        pygame.draw.rect(surf, COLOR_COIN_DARK, (9, 7, 2, 10))
    return surf


# --- GAME OBJECT CLASSES ---

class Player(pygame.sprite.Sprite):
    """The Mario player character with physics, collision, and animation."""
    def __init__(self, x, y):
        super().__init__()
        self.spawn_x = x
        self.spawn_y = y
        self.image = create_mario_surface('idle', True)
        self.rect = pygame.Rect(x, y, 30, 40)

        # Movement / Physics state
        self.vel_x = 0.0
        self.vel_y = 0.0
        self.on_ground = False
        self.facing_right = True
        self.is_running = False

        # Gameplay state
        self.is_alive = True
        self.lives = 3
        self.score = 0
        self.coins = 0
        self.invulnerable_timer = 0
        self.dead_timer = 0

        # Animation state
        self.anim_timer = 0
        self.walk_frame = 0

    def reset_position(self):
        self.rect.x = self.spawn_x
        self.rect.y = self.spawn_y
        self.vel_x = 0.0
        self.vel_y = 0.0
        self.on_ground = False
        self.is_alive = True
        self.dead_timer = 0
        self.invulnerable_timer = 60

    def handle_input(self, keys):
        if not self.is_alive:
            return

        self.is_running = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or keys[pygame.K_x]
        max_speed = MAX_RUN_SPEED if self.is_running else MAX_WALK_SPEED
        accel = RUN_ACCEL if self.is_running else WALK_ACCEL

        # Horizontal movement
        moving = False
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.vel_x -= accel
            if self.vel_x < -max_speed:
                self.vel_x = -max_speed
            self.facing_right = False
            moving = True
        elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.vel_x += accel
            if self.vel_x > max_speed:
                self.vel_x = max_speed
            self.facing_right = True
            moving = True

        if not moving:
            # Friction
            if self.vel_x > 0:
                self.vel_x = max(0.0, self.vel_x - FRICTION)
            elif self.vel_x < 0:
                self.vel_x = min(0.0, self.vel_x + FRICTION)

        # Jump
        jump_pressed = keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]
        if jump_pressed and self.on_ground:
            self.jump()

    def jump(self):
        if self.on_ground and self.is_alive:
            self.vel_y = JUMP_FORCE
            self.on_ground = False
            sound_manager.play('jump')

    def cut_jump(self):
        """Variable jump height: cut jump short when button released."""
        if self.vel_y < -4.0:
            self.vel_y *= 0.5

    def bounce(self):
        """Bounce off an enemy."""
        self.vel_y = BOUNCE_FORCE
        self.on_ground = False
        sound_manager.play('stomp')

    def die(self):
        if not self.is_alive:
            return
        self.is_alive = False
        self.vel_y = -11.0
        self.vel_x = 0.0
        self.lives -= 1
        self.dead_timer = 90
        sound_manager.play('die')

    def update(self, platforms):
        if not self.is_alive:
            # Death jump physics
            self.vel_y += GRAVITY
            self.rect.y += int(self.vel_y)
            self.dead_timer -= 1
            self.image = create_mario_surface('dead', self.facing_right)
            return

        if self.invulnerable_timer > 0:
            self.invulnerable_timer -= 1

        # 1. Horizontal movement and collision
        self.rect.x += int(self.vel_x)
        for platform in platforms:
            if self.rect.colliderect(platform.rect):
                if self.vel_x > 0:
                    self.rect.right = platform.rect.left
                    self.vel_x = 0
                elif self.vel_x < 0:
                    self.rect.left = platform.rect.right
                    self.vel_x = 0

        # Prevent moving left beyond world boundary
        if self.rect.left < 0:
            self.rect.left = 0
            self.vel_x = 0

        # 2. Vertical movement and gravity
        if self.on_ground:
            # Check if player is still supported by a platform beneath
            ground_check = self.rect.move(0, 1)
            is_supported = any(ground_check.colliderect(p.rect) for p in platforms)
            if not is_supported:
                self.on_ground = False

        if not self.on_ground:
            self.vel_y = min(self.vel_y + GRAVITY, MAX_FALL_SPEED)
            self.rect.y += int(self.vel_y)

            for platform in platforms:
                if self.rect.colliderect(platform.rect):
                    if self.vel_y > 0:
                        # Landing on top of platform
                        self.rect.bottom = platform.rect.top
                        self.vel_y = 0.0
                        self.on_ground = True
                    elif self.vel_y < 0:
                        # Hitting ceiling
                        self.rect.top = platform.rect.bottom
                        self.vel_y = 0.0
                        # Check if platform can be bumped
                        if hasattr(platform, 'hit'):
                            platform.hit(self)

        # 3. Death boundary (falling into pits)
        if self.rect.top > DEATH_Y:
            self.die()

        # 4. Animation
        self._update_animation()

    def _update_animation(self):
        if not self.on_ground:
            self.image = create_mario_surface('jump', self.facing_right)
        elif abs(self.vel_x) > 0.5:
            self.anim_timer += 1
            stride = 6 if self.is_running else 10
            if self.anim_timer >= stride:
                self.anim_timer = 0
                self.walk_frame = (self.walk_frame + 1) % 2
            state = 'walk_2' if self.walk_frame == 1 else 'idle'
            self.image = create_mario_surface(state, self.facing_right)
        else:
            self.image = create_mario_surface('idle', self.facing_right)

        # Blink when invulnerable
        if self.invulnerable_timer > 0 and (self.invulnerable_timer // 4) % 2 == 0:
            self.image = self.image.copy()
            self.image.set_alpha(100)


class Platform(pygame.sprite.Sprite):
    """Base class for solid level platforms."""
    def __init__(self, x, y, width, height, color=COLOR_GROUND_DIRT):
        super().__init__()
        self.rect = pygame.Rect(x, y, width, height)
        self.image = pygame.Surface((width, height))
        self.image.fill(color)
        self._decorate(width, height)

    def _decorate(self, width, height):
        # Top green border for ground
        pygame.draw.rect(self.image, COLOR_GROUND_GRASS, (0, 0, width, min(8, height)))
        # Inner outline
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 0, width, height), 1)


class Brick(Platform):
    """Solid brick block that can be bumped from underneath."""
    def __init__(self, x, y):
        super().__init__(x, y, 32, 32, COLOR_BRICK)
        self.original_y = y
        self.bump_offset = 0
        self._render_brick()

    def _render_brick(self):
        self.image.fill(COLOR_BRICK)
        # Mortar lines
        pygame.draw.line(self.image, COLOR_BRICK_DARK, (0, 16), (32, 16), 2)
        pygame.draw.line(self.image, COLOR_BRICK_DARK, (16, 0), (16, 16), 2)
        pygame.draw.line(self.image, COLOR_BRICK_DARK, (8, 16), (8, 32), 2)
        pygame.draw.line(self.image, COLOR_BRICK_DARK, (24, 16), (24, 32), 2)
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 0, 32, 32), 1)

    def hit(self, player):
        sound_manager.play('bump')
        self.bump_offset = -6

    def update(self):
        if self.bump_offset < 0:
            self.bump_offset += 1
            self.rect.y = self.original_y + self.bump_offset


class QuestionBlock(Platform):
    """Mystery question block holding coins or items."""
    def __init__(self, x, y, has_coin=True):
        super().__init__(x, y, 32, 32, COLOR_QUESTION_BLOCK)
        self.has_coin = has_coin
        self.is_hit = False
        self.original_y = y
        self.bump_offset = 0
        self._render_block()

    def _render_block(self):
        self.image.fill(COLOR_QUESTION_HIT if self.is_hit else COLOR_QUESTION_BLOCK)
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 0, 32, 32), 2)

        if not self.is_hit:
            # Rivets in corners
            for rx, ry in [(3, 3), (25, 3), (3, 25), (25, 25)]:
                pygame.draw.rect(self.image, COLOR_BLACK, (rx, ry, 3, 3))
            # Question mark '?'
            pygame.draw.rect(self.image, COLOR_WHITE, (10, 8, 12, 4))
            pygame.draw.rect(self.image, COLOR_WHITE, (18, 12, 4, 4))
            pygame.draw.rect(self.image, COLOR_WHITE, (12, 16, 8, 4))
            pygame.draw.rect(self.image, COLOR_WHITE, (14, 22, 4, 4))
        else:
            # Hit brown block with corner rivets
            for rx, ry in [(4, 4), (24, 4), (4, 24), (24, 24)]:
                pygame.draw.rect(self.image, COLOR_BLACK, (rx, ry, 3, 3))

    def hit(self, player):
        if not self.is_hit:
            self.is_hit = True
            self._render_block()
            self.bump_offset = -8
            if self.has_coin:
                player.coins += 1
                player.score += 200
                sound_manager.play('coin')
            else:
                sound_manager.play('bump')
        else:
            sound_manager.play('bump')

    def update(self):
        if self.bump_offset < 0:
            self.bump_offset += 1
            self.rect.y = self.original_y + self.bump_offset


class Pipe(Platform):
    """Green warp pipe obstacle."""
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height, COLOR_PIPE_GREEN)
        self._render_pipe(width, height)

    def _render_pipe(self, width, height):
        self.image.fill(COLOR_PIPE_GREEN)
        # Pipe rim / top collar
        rim_height = min(24, height)
        pygame.draw.rect(self.image, COLOR_PIPE_LIGHT, (4, 0, 8, height))
        pygame.draw.rect(self.image, COLOR_PIPE_DARK, (width - 12, 0, 10, height))
        # Collar top
        pygame.draw.rect(self.image, COLOR_PIPE_GREEN, (0, 0, width, rim_height))
        pygame.draw.rect(self.image, COLOR_PIPE_LIGHT, (4, 0, 8, rim_height))
        pygame.draw.rect(self.image, COLOR_PIPE_DARK, (width - 12, 0, 10, rim_height))
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 0, width, rim_height), 2)
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 0, width, height), 2)


class Coin(pygame.sprite.Sprite):
    """Floating collectible gold coin."""
    def __init__(self, x, y):
        super().__init__()
        self.rect = pygame.Rect(x, y, 20, 24)
        self.frame = 0
        self.anim_timer = 0
        self.image = create_coin_surface(0)

    def update(self):
        self.anim_timer += 1
        if self.anim_timer >= 8:
            self.anim_timer = 0
            self.frame = (self.frame + 1) % 4
            self.image = create_coin_surface(self.frame)

    def collect(self, player):
        player.coins += 1
        player.score += 200
        sound_manager.play('coin')
        self.kill()


class Enemy(pygame.sprite.Sprite):
    """Patrolling Goomba enemy that walks back and forth and can be stomped."""
    def __init__(self, x, y, patrol_range=150):
        super().__init__()
        self.rect = pygame.Rect(x, y, 32, 32)
        self.vel_x = -1.6
        self.vel_y = 0.0
        self.patrol_left = x - patrol_range
        self.patrol_right = x + patrol_range
        self.is_alive = True
        self.squished = False
        self.squish_timer = 0
        self.image = create_goomba_surface(False)

    def stomp(self):
        self.is_alive = False
        self.squished = True
        self.squish_timer = 30
        self.vel_x = 0
        self.vel_y = 0
        self.image = create_goomba_surface(True)
        self.rect.height = 14
        self.rect.y += 18

    def update(self, platforms):
        if self.squished:
            self.squish_timer -= 1
            if self.squish_timer <= 0:
                self.kill()
            return

        if not self.is_alive:
            self.kill()
            return

        # 1. Horizontal movement
        self.rect.x += int(self.vel_x)
        # Turn around at patrol limits
        if self.rect.left < self.patrol_left:
            self.rect.left = self.patrol_left
            self.vel_x = abs(self.vel_x)
        elif self.rect.right > self.patrol_right:
            self.rect.right = self.patrol_right
            self.vel_x = -abs(self.vel_x)

        # Turn around if hitting solid walls/pipes
        for platform in platforms:
            if self.rect.colliderect(platform.rect):
                if self.vel_x > 0:
                    self.rect.right = platform.rect.left
                    self.vel_x = -abs(self.vel_x)
                elif self.vel_x < 0:
                    self.rect.left = platform.rect.right
                    self.vel_x = abs(self.vel_x)

        # 2. Vertical movement & gravity
        ground_check = self.rect.move(0, 1)
        on_ground = any(ground_check.colliderect(p.rect) for p in platforms)
        if not on_ground:
            self.vel_y = min(self.vel_y + GRAVITY, MAX_FALL_SPEED)
            self.rect.y += int(self.vel_y)

            for platform in platforms:
                if self.rect.colliderect(platform.rect):
                    if self.vel_y > 0:
                        self.rect.bottom = platform.rect.top
                        self.vel_y = 0.0
        else:
            self.vel_y = 0.0

        # Die if falling into pit
        if self.rect.top > DEATH_Y:
            self.kill()


class Flagpole(pygame.sprite.Sprite):
    """End-of-level goal pole."""
    def __init__(self, x, y, height=320):
        super().__init__()
        self.rect = pygame.Rect(x, y, 20, height)
        self.flag_y = y + 10
        self.pole_top = y
        self.pole_bottom = y + height
        self.flag_descending = False
        self.reached = False

        self.image = pygame.Surface((48, height), pygame.SRCALPHA)
        self._render_pole(height)

    def _render_pole(self, height):
        self.image.fill((0, 0, 0, 0))
        # Golden ball top
        pygame.draw.circle(self.image, COLOR_COIN_GOLD, (10, 10), 10)
        # Silver pole
        pygame.draw.rect(self.image, (210, 210, 210), (7, 18, 6, height - 18))
        pygame.draw.rect(self.image, COLOR_BLACK, (7, 18, 6, height - 18), 1)
        # Flag
        flag_rel_y = self.flag_y - self.pole_top
        points = [(13, flag_rel_y), (45, flag_rel_y + 16), (13, flag_rel_y + 32)]
        pygame.draw.polygon(self.image, COLOR_MARIO_RED, points)
        pygame.draw.polygon(self.image, COLOR_WHITE, points, 2)

    def touch(self, player):
        if not self.reached:
            self.reached = True
            self.flag_descending = True
            player.score += 1000
            sound_manager.play('win')

    def update(self):
        if self.flag_descending:
            if self.flag_y < self.pole_bottom - 48:
                self.flag_y += 4
                self._render_pole(self.rect.height)
            else:
                self.flag_descending = False


class Castle(pygame.sprite.Sprite):
    """Castle structure at the end of the stage."""
    def __init__(self, x, y):
        super().__init__()
        width = 160
        height = 160
        self.rect = pygame.Rect(x, y, width, height)
        self.image = pygame.Surface((width, height), pygame.SRCALPHA)
        self._render_castle(width, height)

    def _render_castle(self, w, h):
        # Base walls
        pygame.draw.rect(self.image, COLOR_BRICK, (0, 40, w, h - 40))
        # Battlements
        for i in range(5):
            pygame.draw.rect(self.image, COLOR_BRICK, (i * 32, 20, 24, 20))
        # Central tower
        pygame.draw.rect(self.image, COLOR_BRICK, (48, 0, 64, 40))
        for i in range(2):
            pygame.draw.rect(self.image, COLOR_BRICK, (48 + i * 36, -10, 20, 10))
        # Door
        pygame.draw.ellipse(self.image, COLOR_BLACK, (60, h - 60, 40, 60))
        # Mortar details
        pygame.draw.rect(self.image, COLOR_BLACK, (0, 40, w, h - 40), 2)


# --- CAMERA ---
class Camera:
    """Side-scrolling camera that follows Mario."""
    def __init__(self, level_width, level_height):
        self.level_width = level_width
        self.level_height = level_height
        self.x = 0

    def update(self, target_rect):
        # Center Mario horizontally on screen
        target_x = target_rect.centerx - SCREEN_WIDTH // 3
        # Mario cannot scroll backwards past current left position
        self.x = max(self.x, target_x)
        # Clamp camera to level edges
        self.x = max(0, min(self.x, self.level_width - SCREEN_WIDTH))

    def apply(self, rect):
        """Returns offset rectangle for rendering."""
        return rect.move(-self.x, 0)


# --- LEVEL BUILDER ---
class Level:
    """Builds and holds all entities for a platformer stage."""
    def __init__(self):
        self.width = 3400
        self.height = SCREEN_HEIGHT

        self.platforms = pygame.sprite.Group()
        self.coins = pygame.sprite.Group()
        self.enemies = pygame.sprite.Group()
        self.animated_blocks = pygame.sprite.Group()
        self.scenery = []
        self.flagpole = None
        self.castle = None

        self._build_level()

    def _build_level(self):
        # 1. Ground segments with pits
        ground_segments = [
            (0, 920),         # Starting area
            (1050, 850),      # Middle section after pit 1
            (2050, 1350),     # Castle approach after pit 2
        ]
        for gx, gw in ground_segments:
            ground = Platform(gx, 500, gw, 100)
            self.platforms.add(ground)

        # 2. Mystery / Question Blocks and Bricks
        blocks_data = [
            # First set of blocks
            (QuestionBlock, 280, 360, True),
            (Brick, 340, 360),
            (QuestionBlock, 372, 360, True),
            (Brick, 404, 360),
            (QuestionBlock, 436, 360, True),
            (Brick, 468, 360),
            # High mystery block
            (QuestionBlock, 372, 220, True),

            # Mid-level elevated platforms
            (Brick, 800, 360),
            (Brick, 832, 360),
            (Brick, 864, 360),
            (QuestionBlock, 896, 360, True),

            # Island platforms over pit
            (Platform, 950, 420, 70, 20),

            # Second set of blocks
            (Brick, 1200, 360),
            (QuestionBlock, 1232, 360, True),
            (Brick, 1264, 360),
            (Brick, 1350, 240),
            (Brick, 1382, 240),
            (Brick, 1414, 240),
            (QuestionBlock, 1446, 240, True),

            # Staircase up to flagpole
            (Brick, 2600, 468),
            (Brick, 2632, 468), (Brick, 2632, 436),
            (Brick, 2664, 468), (Brick, 2664, 436), (Brick, 2664, 404),
            (Brick, 2696, 468), (Brick, 2696, 436), (Brick, 2696, 404), (Brick, 2696, 372),
        ]
        for item in blocks_data:
            cls = item[0]
            if cls is QuestionBlock:
                blk = QuestionBlock(item[1], item[2], item[3])
                self.platforms.add(blk)
                self.animated_blocks.add(blk)
            elif cls is Brick:
                blk = Brick(item[1], item[2])
                self.platforms.add(blk)
                self.animated_blocks.add(blk)
            elif cls is Platform:
                blk = Platform(item[1], item[2], item[3], item[4])
                self.platforms.add(blk)

        # 3. Pipes
        pipes_data = [
            (560, 436, 48, 64),
            (720, 404, 48, 96),
            (1150, 420, 48, 80),
            (1600, 388, 48, 112),
            (2250, 420, 48, 80),
        ]
        for px, py, pw, ph in pipes_data:
            pipe = Pipe(px, py, pw, ph)
            self.platforms.add(pipe)

        # 4. Floating Coins
        coin_coords = [
            (310, 310), (345, 310), (410, 310), (440, 310),
            (574, 380), (734, 350),
            (810, 310), (842, 310), (874, 310),
            (970, 370),
            (1360, 190), (1392, 190), (1424, 190),
            (1614, 330),
            (1850, 400), (1900, 370), (1950, 400),
            (2300, 450), (2350, 450), (2400, 450),
        ]
        for cx, cy in coin_coords:
            self.coins.add(Coin(cx, cy))

        # 5. Enemies (Goombas)
        enemies_data = [
            (480, 468, 160),
            (650, 468, 120),
            (1100, 468, 80),
            (1300, 468, 140),
            (1450, 468, 150),
            (1750, 468, 180),
            (2150, 468, 120),
            (2400, 468, 140),
        ]
        for ex, ey, patrol in enemies_data:
            self.enemies.add(Enemy(ex, ey, patrol))

        # 6. Flagpole & Castle
        self.flagpole = Flagpole(2900, 180, 320)
        self.castle = Castle(3020, 340)

        # 7. Scenery: clouds and bushes
        for cx in range(100, 3200, 350):
            self.scenery.append(('cloud', cx, 80 + (cx % 70)))
        for bx in range(150, 3200, 400):
            self.scenery.append(('bush', bx, 468))


# --- GAME ENGINE ---
class Game:
    """Main game manager with game loop, state transitions, and rendering."""
    STATE_MENU = 'MENU'
    STATE_PLAYING = 'PLAYING'
    STATE_GAME_OVER = 'GAME_OVER'
    STATE_VICTORY = 'VICTORY'

    def __init__(self, headless=False):
        safe_init()
        self.headless = headless
        if not self.headless:
            try:
                self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
                pygame.display.set_caption("Super Mario - Complete 2D Platformer")
            except pygame.error:
                self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        else:
            self.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        try:
            self.font = pygame.font.SysFont('Arial', 20, bold=True)
            self.title_font = pygame.font.SysFont('Arial', 44, bold=True)
        except Exception:
            self.font = pygame.font.Font(None, 20)
            self.title_font = pygame.font.Font(None, 44)

        self.state = self.STATE_MENU
        self.reset_game()

    def reset_game(self):
        """Starts a fresh new game."""
        self.level = Level()
        self.player = Player(100, 450)
        self.camera = Camera(self.level.width, self.level.height)
        self.time_left = 400
        self.frame_count = 0
        self.state = self.STATE_PLAYING

    def reset_level_on_death(self):
        """Respawns player after losing a life."""
        if self.player.lives > 0:
            self.player.reset_position()
            self.camera.x = 0
        else:
            self.state = self.STATE_GAME_OVER

    def handle_events(self):
        """Processes keyboard and window events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
                    return False

                if self.state == self.STATE_MENU:
                    if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                        self.reset_game()

                elif self.state in (self.STATE_GAME_OVER, self.STATE_VICTORY):
                    if event.key == pygame.K_r or event.key == pygame.K_RETURN:
                        self.reset_game()

            if event.type == pygame.KEYUP:
                if self.state == self.STATE_PLAYING:
                    if event.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                        self.player.cut_jump()

        return True

    def update(self):
        """Updates game state, physics, collisions, and timer."""
        if self.state != self.STATE_PLAYING:
            return

        # Time countdown
        self.frame_count += 1
        if self.frame_count % FPS == 0:
            self.time_left = max(0, self.time_left - 1)
            if self.time_left == 0 and self.player.is_alive:
                self.player.die()

        # Handle player continuous keyboard input
        keys = pygame.key.get_pressed()
        self.player.handle_input(keys)

        # Update player physics and collisions with platforms
        self.player.update(self.level.platforms)

        # Check death respawn timer
        if not self.player.is_alive and self.player.dead_timer <= 0:
            self.reset_level_on_death()
            return

        # Update level elements
        self.level.platforms.update()
        self.level.coins.update()
        self.level.enemies.update(self.level.platforms)
        self.level.flagpole.update()

        # Check coin collection
        coins_hit = pygame.sprite.spritecollide(self.player, self.level.coins, False)
        for coin in coins_hit:
            coin.collect(self.player)

        # Check enemy interactions
        if self.player.is_alive:
            for enemy in list(self.level.enemies):
                if not enemy.is_alive:
                    continue
                if self.player.rect.colliderect(enemy.rect):
                    # Check if Mario stomps on enemy from above
                    # Condition: Mario is falling downward and player's bottom is near enemy top
                    if self.player.vel_y > 0 and self.player.rect.bottom <= enemy.rect.top + 16:
                        enemy.stomp()
                        self.player.bounce()
                        self.player.score += 100
                    elif self.player.invulnerable_timer <= 0:
                        # Mario touched enemy from side or bottom
                        self.player.die()

        # Check flagpole goal
        if self.player.is_alive and self.player.rect.colliderect(self.level.flagpole.rect):
            self.level.flagpole.touch(self.player)
            self.state = self.STATE_VICTORY

        # Update camera
        self.camera.update(self.player.rect)

    def draw(self):
        """Renders the game scene, HUD, and menus."""
        self.screen.fill(COLOR_SKY)

        if self.state == self.STATE_MENU:
            self._draw_menu()
        elif self.state in (self.STATE_PLAYING, self.STATE_GAME_OVER, self.STATE_VICTORY):
            self._draw_world()
            self._draw_hud()

            if self.state == self.STATE_GAME_OVER:
                self._draw_overlay("GAME OVER", "Press R to Restart")
            elif self.state == self.STATE_VICTORY:
                self._draw_overlay("STAGE CLEAR!", f"Final Score: {self.player.score}  -  Press R to Play Again")

        if not self.headless and pygame.display.get_init() and pygame.display.get_surface() is not None:
            pygame.display.flip()

    def _draw_world(self):
        # Draw background scenery
        for kind, sx, sy in self.level.scenery:
            screen_x = sx - self.camera.x
            if -100 <= screen_x <= SCREEN_WIDTH + 100:
                if kind == 'cloud':
                    pygame.draw.ellipse(self.screen, COLOR_WHITE, (screen_x, sy, 70, 30))
                    pygame.draw.ellipse(self.screen, COLOR_WHITE, (screen_x + 20, sy - 15, 50, 40))
                elif kind == 'bush':
                    pygame.draw.ellipse(self.screen, COLOR_GROUND_GRASS, (screen_x, sy, 60, 32))
                    pygame.draw.ellipse(self.screen, COLOR_GROUND_GRASS, (screen_x + 15, sy - 10, 40, 32))

        # Draw flagpole and castle
        if self.level.flagpole:
            flag_rect = self.camera.apply(self.level.flagpole.rect)
            self.screen.blit(self.level.flagpole.image, flag_rect)

        if self.level.castle:
            castle_rect = self.camera.apply(self.level.castle.rect)
            self.screen.blit(self.level.castle.image, castle_rect)

        # Draw platforms
        for platform in self.level.platforms:
            plat_rect = self.camera.apply(platform.rect)
            if plat_rect.right >= 0 and plat_rect.left <= SCREEN_WIDTH:
                self.screen.blit(platform.image, plat_rect)

        # Draw coins
        for coin in self.level.coins:
            coin_rect = self.camera.apply(coin.rect)
            if coin_rect.right >= 0 and coin_rect.left <= SCREEN_WIDTH:
                self.screen.blit(coin.image, coin_rect)

        # Draw enemies
        for enemy in self.level.enemies:
            enemy_rect = self.camera.apply(enemy.rect)
            if enemy_rect.right >= 0 and enemy_rect.left <= SCREEN_WIDTH:
                self.screen.blit(enemy.image, enemy_rect)

        # Draw player
        player_rect = self.camera.apply(self.player.rect)
        self.screen.blit(self.player.image, player_rect)

    def _draw_hud(self):
        score_txt = self.font.render(f"MARIO   {self.player.score:06d}", True, COLOR_WHITE)
        coin_txt = self.font.render(f"COINS  x{self.player.coins:02d}", True, COLOR_WHITE)
        world_txt = self.font.render("WORLD  1-1", True, COLOR_WHITE)
        time_txt = self.font.render(f"TIME   {self.time_left:03d}", True, COLOR_WHITE)
        lives_txt = self.font.render(f"LIVES  x{self.player.lives}", True, COLOR_WHITE)

        self.screen.blit(score_txt, (30, 15))
        self.screen.blit(coin_txt, (200, 15))
        self.screen.blit(world_txt, (380, 15))
        self.screen.blit(time_txt, (540, 15))
        self.screen.blit(lives_txt, (680, 15))

    def _draw_menu(self):
        title = self.title_font.render("SUPER MARIO", True, COLOR_MARIO_RED)
        subtitle = self.font.render("2D Platformer in Pygame", True, COLOR_WHITE)
        prompt = self.font.render("Press SPACE or ENTER to Start", True, COLOR_COIN_GOLD)

        ctrl1 = self.font.render("CONTROLS:", True, COLOR_WHITE)
        ctrl2 = self.font.render("A / D or LEFT / RIGHT : Move", True, COLOR_WHITE)
        ctrl3 = self.font.render("SPACE / W / UP : Jump (hold for higher jump)", True, COLOR_WHITE)
        ctrl4 = self.font.render("SHIFT or X : Sprint", True, COLOR_WHITE)
        ctrl5 = self.font.render("Stomp enemies to defeat them! Collect coins & reach the flag!", True, COLOR_WHITE)

        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 120))
        self.screen.blit(subtitle, (SCREEN_WIDTH // 2 - subtitle.get_width() // 2, 180))
        self.screen.blit(prompt, (SCREEN_WIDTH // 2 - prompt.get_width() // 2, 240))

        y = 320
        for line in [ctrl1, ctrl2, ctrl3, ctrl4, ctrl5]:
            self.screen.blit(line, (SCREEN_WIDTH // 2 - line.get_width() // 2, y))
            y += 32

    def _draw_overlay(self, title_text, sub_text):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        title = self.title_font.render(title_text, True, COLOR_COIN_GOLD)
        sub = self.font.render(sub_text, True, COLOR_WHITE)
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, SCREEN_HEIGHT // 2 - 40))
        self.screen.blit(sub, (SCREEN_WIDTH // 2 - sub.get_width() // 2, SCREEN_HEIGHT // 2 + 20))

    def run(self):
        """Main game loop."""
        running = True
        while running:
            running = self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == '__main__':
    game = Game()
    game.run()
