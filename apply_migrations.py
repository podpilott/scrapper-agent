#!/usr/bin/env python3
"""
Display database migrations that need to be applied to Supabase.
"""

from pathlib import Path

def main():
    """Display migrations."""
    # Get migrations directory
    migrations_dir = Path(__file__).parent / "supabase" / "migrations"

    # Get migration files (only the new ones we just created)
    new_migrations = [
        migrations_dir / "009_user_preferences.sql",
        migrations_dir / "010_add_language_to_jobs.sql",
    ]

    print("=== Database Migrations for Indonesian Language Support ===\n")
    print("The following migrations need to be applied:\n")

    for migration_file in new_migrations:
        if migration_file.exists():
            print(f"  ✓ {migration_file.name}")

    print("\n" + "="*70)
    print("\nTo apply these migrations, you have two options:\n")
    print("Option 1: Supabase Dashboard (Recommended)")
    print("  1. Go to: https://supabase.com/dashboard")
    print("  2. Select your project")
    print("  3. Go to SQL Editor")
    print("  4. Copy and paste the SQL from each file below")
    print("  5. Click 'Run'\n")

    print("Option 2: psql command line")
    print("  psql postgresql://[CONNECTION_STRING] < supabase/migrations/009_user_preferences.sql")
    print("  psql postgresql://[CONNECTION_STRING] < supabase/migrations/010_add_language_to_jobs.sql\n")

    # Print the actual SQL
    for migration_file in new_migrations:
        if migration_file.exists():
            print(f"\n{'='*70}")
            print(f"File: {migration_file.name}")
            print(f"{'='*70}\n")
            with open(migration_file, 'r') as f:
                print(f.read())
            print(f"\n{'='*70}\n")

if __name__ == "__main__":
    main()
