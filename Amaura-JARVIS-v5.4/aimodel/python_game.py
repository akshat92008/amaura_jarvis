import random
import time

def start_game():
    print("===================================================")
    print("🎮 WELCOME TO FABLE-5 CYBER SPACE ADVENTURE GAME 🎮")
    print("===================================================")
    score = 0
    health = 100
    print("System Initialized... Navigating Cyber Grid.")
    for turn in range(1, 6):
        time.sleep(0.5)
        print(f"\n--- Sector {turn} ---")
        event = random.choice(['enemy', 'treasure', 'glitch'])
        if event == 'enemy':
            damage = random.randint(10, 25)
            health -= damage
            print(f"👾 Encountered Firewall Sentinel! Took {damage} damage. Health: {health}")
        elif event == 'treasure':
            points = random.randint(20, 50)
            score += points
            print(f"💎 Discovered Quantum Data Core! +{points} pts. Score: {score}")
        else:
            print("⚡ Quantum Flux Matrix Stabilized. Path Clear.")
        if health <= 0:
            print("\n❌ GAME OVER: System Compromised!")
            return
    print("\n===================================================")
    print(f"🏆 MISSION ACCOMPLISHED! Final Score: {score} | Health: {health}")
    print("===================================================")

if __name__ == '__main__':
    start_game()
