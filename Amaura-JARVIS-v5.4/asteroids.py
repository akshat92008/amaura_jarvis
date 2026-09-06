"""
Asteroids Arcade Game
=====================
A complete playable Asteroids arcade game built with Pygame.

Features:
- Player ship rotation and inertia-based thrust physics
- Screen wrapping across all edges for ship, asteroids, and projectiles
- Splitting rock asteroids (Large -> Medium -> Small -> Destroyed)
- Laser projectile shooting with cooldown and lifetime mechanics
- Score tracking, high score tracking, lives, and level wave progression
"""

import math
import random
import sys
import pygame

# -----------------------------------------------------------------------------
# Configuration Constants
# -----------------------------------------------------------------------------
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 60, 60)
GREEN = (60, 255, 60)
BLUE = (60, 160, 255)
YELLOW = (255, 220, 50)
GRAY = (140, 140, 140)

# Asteroid Stages / Sizes
ASTEROID_LARGE = 3
ASTEROID_MEDIUM = 2
ASTEROID_SMALL = 1

ASTEROID_RADII = {
    ASTEROID_LARGE: 40.0,
    ASTEROID_MEDIUM: 20.0,
    ASTEROID_SMALL: 10.0,
}

ASTEROID_SCORES = {
    ASTEROID_LARGE: 20,
    ASTEROID_MEDIUM: 50,
    ASTEROID_SMALL: 100,
}

ASTEROID_SPEEDS = {
    ASTEROID_LARGE: (1.0, 2.0),
    ASTEROID_MEDIUM: (2.0, 3.5),
    ASTEROID_SMALL: (3.0, 5.0),
}


# -----------------------------------------------------------------------------
# Helper Utilities
# -----------------------------------------------------------------------------
def wrap_position(x: float, y: float, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT) -> tuple[float, float]:
    """Wrap coordinates around screen boundaries."""
    return x % width, y % height


class AsteroidSize(int):
    """Integer subclass for asteroid size allowing comparisons with int and strings."""
    def __eq__(self, other):
        if isinstance(other, str):
            mapping = {ASTEROID_LARGE: "large", ASTEROID_MEDIUM: "medium", ASTEROID_SMALL: "small"}
            return mapping.get(int(self), "").lower() == other.lower()
        return super().__eq__(other)

    def __hash__(self):
        return super().__hash__()


# -----------------------------------------------------------------------------
# Game Entities
# -----------------------------------------------------------------------------
class Laser:
    """Laser projectile fired by the ship."""
    def __init__(
        self,
        x: float,
        y: float,
        angle: float = 0.0,
        speed: float = 10.0,
        velocity_x: float = None,
        velocity_y: float = None,
        lifetime: int = 60,
        screen_width: int = SCREEN_WIDTH,
        screen_height: int = SCREEN_HEIGHT,
        radius: float = 2.5,
    ):
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle)
        self.speed = float(speed)
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.radius = float(radius)
        self.lifetime = int(lifetime)
        self.max_lifetime = int(lifetime)
        self.age = 0
        self.is_alive = True

        if velocity_x is not None and velocity_y is not None:
            self.velocity_x = float(velocity_x)
            self.velocity_y = float(velocity_y)
        else:
            rad = math.radians(self.angle)
            self.velocity_x = math.sin(rad) * self.speed
            self.velocity_y = -math.cos(rad) * self.speed

    @property
    def vx(self) -> float:
        return self.velocity_x

    @vx.setter
    def vx(self, val: float):
        self.velocity_x = float(val)

    @property
    def vy(self) -> float:
        return self.velocity_y

    @vy.setter
    def vy(self, val: float):
        self.velocity_y = float(val)

    @property
    def alive(self) -> bool:
        return self.is_alive

    @alive.setter
    def alive(self, val: bool):
        self.is_alive = bool(val)

    def update(self, dt: float = 1.0):
        """Update laser position with screen wrapping and lifetime decrement."""
        self.x = (self.x + self.velocity_x * dt) % self.screen_width
        self.y = (self.y + self.velocity_y * dt) % self.screen_height
        self.age += 1
        self.lifetime -= 1
        if self.lifetime <= 0:
            self.is_alive = False

    def collides_with(self, other) -> bool:
        """Check collision with another circular entity."""
        dist = math.hypot(self.x - other.x, self.y - other.y)
        return dist < (self.radius + other.radius)

    def draw(self, surface):
        """Render laser to Pygame surface."""
        if self.is_alive and surface is not None:
            pygame.draw.circle(surface, WHITE, (int(self.x), int(self.y)), max(1, int(self.radius)))


# Alias Bullet to Laser for flexibility
Bullet = Laser


class Asteroid:
    """Splitting rock asteroid."""
    def __init__(
        self,
        x: float = 0.0,
        y: float = 0.0,
        stage: int = ASTEROID_LARGE,
        velocity_x: float = 0.0,
        velocity_y: float = 0.0,
        radius: float = None,
        size: int | str = None,
        screen_width: int = SCREEN_WIDTH,
        screen_height: int = SCREEN_HEIGHT,
    ):
        self.x = float(x)
        self.y = float(y)
        self.velocity_x = float(velocity_x)
        self.velocity_y = float(velocity_y)
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.is_alive = True

        # Parse stage or size
        if size is not None:
            if isinstance(size, str):
                s_lower = size.lower()
                if "large" in s_lower or "3" in s_lower:
                    self.stage = ASTEROID_LARGE
                elif "medium" in s_lower or "2" in s_lower:
                    self.stage = ASTEROID_MEDIUM
                elif "small" in s_lower or "1" in s_lower:
                    self.stage = ASTEROID_SMALL
                else:
                    self.stage = ASTEROID_LARGE
            else:
                self.stage = int(size)
        else:
            self.stage = int(stage)

        # Assign radius
        if radius is not None:
            self.radius = float(radius)
        else:
            self.radius = ASTEROID_RADII.get(self.stage, 20.0)

        # Assign score points
        self.score_value = ASTEROID_SCORES.get(self.stage, 50)

        # Procedural jagged rock outline
        self.vertex_offsets = self._generate_shape()

    def _generate_shape(self) -> list[tuple[float, float]]:
        num_points = 10
        offsets = []
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            variation = 0.8 + 0.4 * ((math.sin(self.x * 0.05 + i * 1.7) + 1.0) / 2.0)
            r = self.radius * variation
            offsets.append((r * math.cos(angle), r * math.sin(angle)))
        return offsets

    @property
    def vx(self) -> float:
        return self.velocity_x

    @vx.setter
    def vx(self, val: float):
        self.velocity_x = float(val)

    @property
    def vy(self) -> float:
        return self.velocity_y

    @vy.setter
    def vy(self, val: float):
        self.velocity_y = float(val)

    @property
    def alive(self) -> bool:
        return self.is_alive

    @alive.setter
    def alive(self, val: bool):
        self.is_alive = bool(val)

    @property
    def points(self) -> int:
        return self.score_value

    @points.setter
    def points(self, val: int):
        self.score_value = int(val)

    @property
    def score(self) -> int:
        return self.score_value

    @property
    def size(self) -> AsteroidSize:
        return AsteroidSize(self.stage)

    @property
    def size_name(self) -> str:
        mapping = {ASTEROID_LARGE: "large", ASTEROID_MEDIUM: "medium", ASTEROID_SMALL: "small"}
        return mapping.get(self.stage, "unknown")

    def update(self, dt: float = 1.0):
        """Update asteroid position with screen wrapping."""
        self.x = (self.x + self.velocity_x * dt) % self.screen_width
        self.y = (self.y + self.velocity_y * dt) % self.screen_height

    def collides_with(self, other) -> bool:
        """Check circular collision."""
        dist = math.hypot(self.x - other.x, self.y - other.y)
        return dist < (self.radius + other.radius)

    def split(self) -> list["Asteroid"]:
        """
        Split asteroid into two smaller pieces upon destruction.
        Large -> 2 Medium, Medium -> 2 Small, Small -> Destroyed.
        """
        if not self.is_alive or self.stage <= ASTEROID_SMALL:
            self.is_alive = False
            return []

        self.is_alive = False
        new_stage = self.stage - 1
        speed_range = ASTEROID_SPEEDS.get(new_stage, (2.0, 4.0))

        base_speed = math.hypot(self.velocity_x, self.velocity_y) * 1.3
        speed = max(base_speed, speed_range[0])
        speed = min(speed, speed_range[1] * 1.5)

        if self.velocity_x != 0 or self.velocity_y != 0:
            current_angle = math.atan2(self.velocity_y, self.velocity_x)
        else:
            current_angle = random.uniform(0, 2 * math.pi)

        angle1 = current_angle + math.pi / 4
        angle2 = current_angle - math.pi / 4

        child1 = Asteroid(
            x=self.x,
            y=self.y,
            stage=new_stage,
            velocity_x=math.cos(angle1) * speed,
            velocity_y=math.sin(angle1) * speed,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        child2 = Asteroid(
            x=self.x,
            y=self.y,
            stage=new_stage,
            velocity_x=math.cos(angle2) * speed,
            velocity_y=math.sin(angle2) * speed,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        return [child1, child2]

    def draw(self, surface):
        """Render asteroid outline to surface."""
        if not self.is_alive or surface is None:
            return
        points = [(self.x + dx, self.y + dy) for dx, dy in self.vertex_offsets]
        pygame.draw.polygon(surface, GRAY, points, 2)


class Ship:
    """Player spaceship with rotation, inertia thrust, and shooting."""
    def __init__(
        self,
        x: float = SCREEN_WIDTH / 2,
        y: float = SCREEN_HEIGHT / 2,
        angle: float = 0.0,
        screen_width: int = SCREEN_WIDTH,
        screen_height: int = SCREEN_HEIGHT,
        radius: float = 15.0,
        rotation_speed: float = 5.0,
        thrust_power: float = 0.2,
        max_speed: float = 8.0,
        friction: float = 1.0,
    ):
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle)
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.radius = float(radius)
        self.rotation_speed = float(rotation_speed)
        self.thrust_power = float(thrust_power)
        self.max_speed = float(max_speed)
        self.friction = float(friction)

        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.shoot_cooldown = 0
        self.fire_cooldown_max = 15
        self.invulnerable_timer = 0
        self.is_thrusting = False
        self.is_alive = True

    @property
    def vx(self) -> float:
        return self.velocity_x

    @vx.setter
    def vx(self, val: float):
        self.velocity_x = float(val)

    @property
    def vy(self) -> float:
        return self.velocity_y

    @vy.setter
    def vy(self, val: float):
        self.velocity_y = float(val)

    @property
    def alive(self) -> bool:
        return self.is_alive

    @alive.setter
    def alive(self, val: bool):
        self.is_alive = bool(val)

    @property
    def heading(self) -> tuple[float, float]:
        """Unit heading vector (0 degrees points UP, negative Y)."""
        rad = math.radians(self.angle)
        return (math.sin(rad), -math.cos(rad))

    def get_heading(self) -> tuple[float, float]:
        return self.heading

    def rotate(self, direction: float = 1.0):
        """Rotate ship angle by direction * rotation_speed."""
        self.angle = (self.angle + direction * self.rotation_speed) % 360.0

    def rotate_left(self, steps: float = 1.0):
        """Rotate ship counter-clockwise."""
        self.rotate(-steps)

    def rotate_right(self, steps: float = 1.0):
        """Rotate ship clockwise."""
        self.rotate(steps)

    def thrust(self, power: float = None):
        """Apply inertia thrust in the direction the ship is facing."""
        p = self.thrust_power if power is None else float(power)
        hx, hy = self.heading
        self.velocity_x += hx * p
        self.velocity_y += hy * p
        speed = math.hypot(self.velocity_x, self.velocity_y)
        if speed > self.max_speed:
            factor = self.max_speed / speed
            self.velocity_x *= factor
            self.velocity_y *= factor
        self.is_thrusting = True

    def apply_thrust(self, power: float = None):
        """Alias for thrust."""
        self.thrust(power)

    def shoot(self, speed: float = 10.0, lifetime: int = 60) -> Laser | None:
        """Fire a laser projectile if cooldown permits."""
        if self.shoot_cooldown > 0 or not self.is_alive:
            return None
        self.shoot_cooldown = self.fire_cooldown_max
        hx, hy = self.heading
        laser_x = self.x + hx * self.radius
        laser_y = self.y + hy * self.radius
        return Laser(
            x=laser_x,
            y=laser_y,
            angle=self.angle,
            speed=speed,
            lifetime=lifetime,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )

    def update(self, dt: float = 1.0):
        """Advance ship position, wrap boundaries, and update cooldowns."""
        self.x = (self.x + self.velocity_x * dt) % self.screen_width
        self.y = (self.y + self.velocity_y * dt) % self.screen_height
        if self.friction != 1.0:
            self.velocity_x *= (self.friction ** dt)
            self.velocity_y *= (self.friction ** dt)

        if self.shoot_cooldown > 0:
            self.shoot_cooldown = max(0, self.shoot_cooldown - 1)
        if self.invulnerable_timer > 0:
            self.invulnerable_timer = max(0, self.invulnerable_timer - 1)
        self.is_thrusting = False

    def reset(self, x: float = None, y: float = None):
        """Reset ship position and physics to center with invulnerability frames."""
        self.x = float(x if x is not None else self.screen_width / 2)
        self.y = float(y if y is not None else self.screen_height / 2)
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.angle = 0.0
        self.shoot_cooldown = 0
        self.invulnerable_timer = 120
        self.is_thrusting = False
        self.is_alive = True

    def is_invulnerable(self) -> bool:
        return self.invulnerable_timer > 0

    def collides_with(self, other) -> bool:
        """Circular collision check."""
        dist = math.hypot(self.x - other.x, self.y - other.y)
        return dist < (self.radius + other.radius)

    def get_vertices(self) -> list[tuple[float, float]]:
        """Calculate ship triangle vertices for rendering."""
        rad = math.radians(self.angle)
        # Nose
        nose = (self.x + self.radius * math.sin(rad), self.y - self.radius * math.cos(rad))
        # Wings
        left_rad = rad + math.radians(140)
        back_left = (self.x + self.radius * math.sin(left_rad), self.y - self.radius * math.cos(left_rad))
        right_rad = rad - math.radians(140)
        back_right = (self.x + self.radius * math.sin(right_rad), self.y - self.radius * math.cos(right_rad))
        return [nose, back_left, back_right]

    def draw(self, surface):
        """Render ship triangle and optional thrust flame."""
        if not self.is_alive or surface is None:
            return
        # Blink when invulnerable
        if self.invulnerable_timer > 0 and (self.invulnerable_timer // 8) % 2 == 1:
            return

        vertices = self.get_vertices()
        pygame.draw.polygon(surface, WHITE, vertices, 2)

        if self.is_thrusting:
            rad = math.radians(self.angle)
            flame_tip = (self.x - self.radius * 1.3 * math.sin(rad), self.y + self.radius * 1.3 * math.cos(rad))
            flame_left = ((vertices[1][0] + vertices[2][0]) / 2 - 3 * math.cos(rad),
                          (vertices[1][1] + vertices[2][1]) / 2 - 3 * math.sin(rad))
            flame_right = ((vertices[1][0] + vertices[2][0]) / 2 + 3 * math.cos(rad),
                           (vertices[1][1] + vertices[2][1]) / 2 + 3 * math.sin(rad))
            pygame.draw.polygon(surface, RED, [flame_left, flame_tip, flame_right])


class Particle:
    """Explosion spark particle."""
    def __init__(self, x: float, y: float, vx: float, vy: float, lifetime: int = 20, color=WHITE):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.lifetime = int(lifetime)
        self.age = 0
        self.color = color
        self.is_alive = True

    def update(self, dt: float = 1.0):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.age += 1
        if self.age >= self.lifetime:
            self.is_alive = False

    def draw(self, surface):
        if self.is_alive and surface is not None:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), 1)


# -----------------------------------------------------------------------------
# Main Game Manager
# -----------------------------------------------------------------------------
class AsteroidsGame:
    """Manages the full Asteroids arcade game state, loop, collisions, and scoring."""
    def __init__(
        self,
        width: int = SCREEN_WIDTH,
        height: int = SCREEN_HEIGHT,
        initial_asteroids: int = 4,
        headless: bool = False,
    ):
        self.screen_width = width
        self.screen_height = height
        self.headless = headless

        self.score = 0
        self.high_score = 0
        self.lives = 3
        self.level = 1
        self.game_over = False

        self.ship = Ship(width / 2, height / 2, screen_width=width, screen_height=height)
        self.asteroids: list[Asteroid] = []
        self.lasers: list[Laser] = []
        self.particles: list[Particle] = []

        if initial_asteroids > 0:
            self.spawn_asteroids(initial_asteroids)

    @property
    def bullets(self) -> list[Laser]:
        return self.lasers

    @bullets.setter
    def bullets(self, val: list[Laser]):
        self.lasers = val

    def spawn_asteroids(self, count: int = 4):
        """Spawn large asteroids away from the player ship."""
        for _ in range(count):
            attempts = 0
            while attempts < 100:
                x = random.uniform(0, self.screen_width)
                y = random.uniform(0, self.screen_height)
                if math.hypot(x - self.ship.x, y - self.ship.y) > 120:
                    break
                attempts += 1
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.0, 2.0)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            self.asteroids.append(
                Asteroid(
                    x=x,
                    y=y,
                    stage=ASTEROID_LARGE,
                    velocity_x=vx,
                    velocity_y=vy,
                    screen_width=self.screen_width,
                    screen_height=self.screen_height,
                )
            )

    def shoot(self) -> Laser | None:
        """Trigger ship laser firing."""
        if self.game_over:
            return None
        laser = self.ship.shoot()
        if laser:
            self.lasers.append(laser)
        return laser

    def add_score(self, points: int):
        """Add points and update high score."""
        self.score += points
        if self.score > self.high_score:
            self.high_score = self.score

    def spawn_explosion(self, x: float, y: float, radius: float = 20.0, count: int = 15):
        """Spawn visual particle debris for destroyed entities."""
        if self.headless:
            return
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.0, 4.0)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            p = Particle(x, y, vx, vy, lifetime=random.randint(15, 30))
            self.particles.append(p)

    def update(self, dt: float = 1.0):
        """Update game state, physics, collisions, and level progression."""
        if self.game_over:
            return

        # 1. Update player ship
        self.ship.update(dt)

        # 2. Update laser projectiles
        for laser in self.lasers:
            laser.update(dt)
        self.lasers = [l for l in self.lasers if l.is_alive]

        # 3. Update asteroids
        for asteroid in self.asteroids:
            asteroid.update(dt)

        # 4. Check laser vs asteroid collisions
        surviving_asteroids = []
        for asteroid in self.asteroids:
            hit = False
            for laser in self.lasers:
                if laser.is_alive and laser.collides_with(asteroid):
                    laser.is_alive = False
                    hit = True
                    self.add_score(asteroid.score_value)
                    pieces = asteroid.split()
                    surviving_asteroids.extend(pieces)
                    self.spawn_explosion(asteroid.x, asteroid.y, asteroid.radius)
                    break
            if not hit:
                surviving_asteroids.append(asteroid)

        self.asteroids = surviving_asteroids
        self.lasers = [l for l in self.lasers if l.is_alive]

        # 5. Check ship vs asteroid collisions
        if not self.ship.is_invulnerable():
            for asteroid in self.asteroids:
                if self.ship.collides_with(asteroid):
                    self.spawn_explosion(self.ship.x, self.ship.y, self.ship.radius * 2, count=25)
                    self.lives -= 1
                    if self.lives <= 0:
                        self.game_over = True
                    else:
                        self.ship.reset()
                    break

        # 6. Check wave complete / progression
        if len(self.asteroids) == 0:
            self.level += 1
            self.spawn_asteroids(min(4 + (self.level - 1) * 2, 12))

        # 7. Update particles
        if not self.headless:
            for p in self.particles:
                p.update(dt)
            self.particles = [p for p in self.particles if p.is_alive]

    def reset(self):
        """Reset game to initial starting state."""
        self.score = 0
        self.lives = 3
        self.level = 1
        self.game_over = False
        self.asteroids.clear()
        self.lasers.clear()
        self.particles.clear()
        self.ship.reset()
        self.ship.invulnerable_timer = 0
        self.spawn_asteroids(4)

    def is_game_over(self) -> bool:
        return self.game_over

    def get_score(self) -> int:
        return self.score

    def get_lives(self) -> int:
        return self.lives

    def get_level(self) -> int:
        return self.level

    def draw(self, surface):
        """Render all game components."""
        if surface is None:
            return
        self.ship.draw(surface)
        for asteroid in self.asteroids:
            asteroid.draw(surface)
        for laser in self.lasers:
            laser.draw(surface)
        for p in self.particles:
            p.draw(surface)


# Class alias
Game = AsteroidsGame


# -----------------------------------------------------------------------------
# Main Playable Game Loop
# -----------------------------------------------------------------------------
def main():
    """Entrypoint for running the playable Asteroids arcade game."""
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Asteroids Arcade")
    clock = pygame.time.Clock()
    game = AsteroidsGame(SCREEN_WIDTH, SCREEN_HEIGHT)

    font = pygame.font.SysFont("monospace", 20, bold=True)
    big_font = pygame.font.SysFont("monospace", 48, bold=True)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    game.shoot()
                elif event.key == pygame.K_r and game.game_over:
                    game.reset()

        keys = pygame.key.get_pressed()
        if not game.game_over:
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                game.ship.rotate_left()
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                game.ship.rotate_right()
            if keys[pygame.K_UP] or keys[pygame.K_w]:
                game.ship.thrust()

        game.update()

        screen.fill(BLACK)
        game.draw(screen)

        # Draw HUD overlays
        score_surf = font.render(f"SCORE: {game.score}", True, WHITE)
        screen.blit(score_surf, (20, 20))
        high_surf = font.render(f"HIGH: {game.high_score}", True, GRAY)
        screen.blit(high_surf, (20, 48))
        lives_surf = font.render(f"LIVES: {game.lives}", True, WHITE)
        screen.blit(lives_surf, (SCREEN_WIDTH - 140, 20))
        level_surf = font.render(f"LEVEL: {game.level}", True, WHITE)
        screen.blit(level_surf, (SCREEN_WIDTH - 140, 48))

        if game.game_over:
            go_surf = big_font.render("GAME OVER", True, RED)
            go_rect = go_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 25))
            screen.blit(go_surf, go_rect)
            rest_surf = font.render("Press 'R' to Restart", True, WHITE)
            rest_rect = rest_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 25))
            screen.blit(rest_surf, rest_rect)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
