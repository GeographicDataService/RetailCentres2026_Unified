#!/usr/bin/env python
"""
Migrate data directory to new structure:
- inputs/     - Source data needed for pipeline
- outputs/    - Run outputs and exports
- intermediate/ - Cached/temporary files

Run with --dry-run first to preview changes.
"""

import argparse
import shutil
from pathlib import Path
from datetime import datetime


def create_directory_structure(base_path: Path, dry_run: bool = False):
    """Create new directory structure."""
    dirs = [
        "inputs/poi",
        "inputs/landuse",
        "inputs/brands",
        "inputs/boundaries",
        "outputs/runs",
        "outputs/arcgis_exports",
        "intermediate/poi_filtered",
        "intermediate/landuse_poi_filtered",
    ]

    print("\n" + "="*80)
    print("CREATING NEW DIRECTORY STRUCTURE")
    print("="*80)

    for dir_path in dirs:
        full_path = base_path / dir_path
        if dry_run:
            print(f"[DRY RUN] Would create: {full_path}")
        else:
            full_path.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created: {full_path}")


def move_file(src: Path, dst: Path, dry_run: bool = False):
    """Move a file from src to dst."""
    if not src.exists():
        print(f"  ⚠ Skip (not found): {src.name}")
        return False

    if dry_run:
        print(f"  [DRY RUN] Would move: {src.name} → {dst}")
        return True
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"  ✓ Moved: {src.name}")
        return True


def migrate_inputs(data_dir: Path, dry_run: bool = False):
    """Migrate files to inputs/ directory."""
    print("\n" + "="*80)
    print("MIGRATING INPUT FILES")
    print("="*80)

    old_input = data_dir / "input_files"
    new_inputs = data_dir / "inputs"

    # POI data
    print("\n📁 POI data → inputs/poi/")
    move_file(
        old_input / "uk_foursquare_cc_nov_iceberg.parquet",
        new_inputs / "poi" / "uk_foursquare_cc_nov_iceberg.parquet",
        dry_run
    )

    # Land use data
    print("\n📁 Land use → inputs/landuse/")
    landuse_files = [
        "retail_landuse.parquet",
        "retail_landuse_h3_geo.parquet",
        "commercial_landuse.parquet",
        "industrial_landuse.parquet",
    ]
    for filename in landuse_files:
        move_file(
            old_input / filename,
            new_inputs / "landuse" / filename,
            dry_run
        )

    # Brand data
    print("\n📁 Brands → inputs/brands/")
    brand_files = [
        "bl_retail_parks_brands_deduped.csv",
        "defunct_uk_retailers_wikipedia_full.csv",
    ]
    for filename in brand_files:
        src = old_input / filename
        # Rename to simpler names
        if "bl_retail_parks" in filename:
            dst_name = "retail_park_brands.csv"
        elif "defunct" in filename:
            dst_name = "defunct_retailers.csv"
        else:
            dst_name = filename

        move_file(src, new_inputs / "brands" / dst_name, dry_run)

    # Boundaries
    print("\n📁 Boundaries → inputs/boundaries/")
    boundaries_dir = data_dir / "Boundaries_lookups"
    if boundaries_dir.exists():
        for gpkg_file in boundaries_dir.glob("*.gpkg"):
            if "Zone.Identifier" not in gpkg_file.name:
                if "Local_Authority" in gpkg_file.name:
                    dst_name = "local_authorities.gpkg"
                else:
                    dst_name = gpkg_file.name
                move_file(gpkg_file, new_inputs / "boundaries" / dst_name, dry_run)


def migrate_outputs(data_dir: Path, dry_run: bool = False):
    """Migrate output files to outputs/runs/ directory."""
    print("\n" + "="*80)
    print("MIGRATING OUTPUT FILES")
    print("="*80)

    old_outputs = data_dir / "output_files"
    new_runs = data_dir / "outputs" / "runs"

    if not old_outputs.exists():
        print("  ⚠ No output_files directory found")
        return

    print("\n📁 Run outputs → outputs/runs/")

    # Move each run folder
    run_count = 0
    for run_dir in old_outputs.iterdir():
        if not run_dir.is_dir():
            continue

        # Skip retail_parks folders (they'll be reorganized)
        if run_dir.name.startswith("retail_parks_"):
            continue

        dst = new_runs / run_dir.name / "centres"

        if dry_run:
            print(f"  [DRY RUN] Would move: {run_dir.name}/ → outputs/runs/{run_dir.name}/centres/")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)

            # Check if this run has parameter combo subdirs or is flat
            has_subdirs = any(p.is_dir() for p in run_dir.iterdir())

            if has_subdirs:
                # Already has parameter combo folders - move as-is
                shutil.move(str(run_dir), str(dst.parent))
                # Create centres subdir and move contents
                centres_dir = new_runs / run_dir.name / "centres"
                centres_dir.mkdir(exist_ok=True)
                for item in (new_runs / run_dir.name).iterdir():
                    if item.is_dir() and item.name != "centres":
                        shutil.move(str(item), str(centres_dir / item.name))
            else:
                # Flat structure - wrap in centres/
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(str(run_dir), str(dst / run_dir.name))

            print(f"  ✓ Moved: {run_dir.name}/")

        run_count += 1

    print(f"\n  Total runs migrated: {run_count}")

    # Move retail_parks folders
    print("\n📁 Retail parks → outputs/runs/{run}/retail_parks/")
    for parks_dir in old_outputs.glob("retail_parks_*"):
        if parks_dir.is_dir():
            # Extract run name from folder (e.g., retail_parks_nov2025v22 → nov2025v22)
            parts = parks_dir.name.split("retail_parks_", 1)
            if len(parts) == 2:
                run_name = parts[1]
                # Check if this matches a run
                matching_run = new_runs / run_name
                if matching_run.exists() or dry_run:
                    dst = new_runs / run_name / "retail_parks"
                    if dry_run:
                        print(f"  [DRY RUN] Would move: {parks_dir.name}/ → outputs/runs/{run_name}/retail_parks/")
                    else:
                        shutil.move(str(parks_dir), str(dst))
                        print(f"  ✓ Moved: {parks_dir.name}/ → {run_name}/retail_parks/")


def migrate_arcgis_exports(data_dir: Path, dry_run: bool = False):
    """Migrate ArcGIS workshop exports to outputs/arcgis_exports/."""
    print("\n" + "="*80)
    print("MIGRATING ARCGIS EXPORTS")
    print("="*80)

    old_arcgis = data_dir / "forarcgis"
    new_arcgis = data_dir / "outputs" / "arcgis_exports"

    if not old_arcgis.exists():
        print("  ⚠ No forarcgis directory found")
        return

    print("\n📁 Workshop files → outputs/arcgis_exports/")

    workshop_count = 0
    for workshop_dir in old_arcgis.iterdir():
        if not workshop_dir.is_dir():
            continue

        if dry_run:
            print(f"  [DRY RUN] Would move: {workshop_dir.name}/")
        else:
            dst = new_arcgis / workshop_dir.name
            shutil.move(str(workshop_dir), str(dst))
            print(f"  ✓ Moved: {workshop_dir.name}/")

        workshop_count += 1

    print(f"\n  Total workshops migrated: {workshop_count}")


def migrate_intermediate(data_dir: Path, dry_run: bool = False):
    """Migrate intermediate files."""
    print("\n" + "="*80)
    print("MIGRATING INTERMEDIATE FILES")
    print("="*80)

    old_poi_files = data_dir / "POI_files"
    new_intermediate = data_dir / "intermediate"

    # Quality filter IDs
    print("\n📁 Filter IDs → intermediate/poi_filtered/")
    move_file(
        old_poi_files / "quality_filter_ids.parquet",
        new_intermediate / "poi_filtered" / "quality_filter_ids.parquet",
        dry_run
    )

    # Filtered landuse
    old_input = data_dir / "input_files"
    print("\n📁 Filtered landuse → intermediate/landuse_poi_filtered/")
    move_file(
        old_input / "retail_landuse_filtered.parquet",
        new_intermediate / "landuse_poi_filtered" / "retail_landuse_filtered.parquet",
        dry_run
    )


def create_backup(data_dir: Path, dry_run: bool = False):
    """Create backup of old structure."""
    print("\n" + "="*80)
    print("CREATING BACKUP")
    print("="*80)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = data_dir / f"_backup_{timestamp}"

    dirs_to_backup = [
        "input_files",
        "output_files",
        "POI_files",
        "forarcgis",
        "Boundaries_lookups",
    ]

    if dry_run:
        print(f"[DRY RUN] Would create backup at: {backup_dir}")
        for dir_name in dirs_to_backup:
            old_dir = data_dir / dir_name
            if old_dir.exists():
                print(f"  [DRY RUN] Would backup: {dir_name}/")
    else:
        backup_dir.mkdir(exist_ok=True)
        print(f"Creating backup at: {backup_dir}")

        for dir_name in dirs_to_backup:
            old_dir = data_dir / dir_name
            if old_dir.exists():
                dst = backup_dir / dir_name
                shutil.copytree(str(old_dir), str(dst))
                print(f"  ✓ Backed up: {dir_name}/")

        print(f"\n✓ Backup created: {backup_dir}")


def cleanup_old_structure(data_dir: Path, dry_run: bool = False):
    """Remove old directories after migration."""
    print("\n" + "="*80)
    print("CLEANING UP OLD STRUCTURE")
    print("="*80)

    dirs_to_remove = [
        "input_files",
        "output_files",
        "POI_files",
        "forarcgis",
        "Boundaries_lookups",
    ]

    for dir_name in dirs_to_remove:
        old_dir = data_dir / dir_name
        if old_dir.exists():
            if dry_run:
                print(f"  [DRY RUN] Would remove: {dir_name}/")
            else:
                shutil.rmtree(str(old_dir))
                print(f"  ✓ Removed: {dir_name}/")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate data directory to new structure"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without actually moving files"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Path to data directory (default: data)"
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip creating backup (not recommended)"
    )

    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    if not data_dir.exists():
        print(f"❌ Error: Data directory not found: {data_dir}")
        return 1

    print("\n" + "="*80)
    print("DATA STRUCTURE MIGRATION")
    print("="*80)
    print(f"Data directory: {data_dir.absolute()}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("="*80)

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No files will be moved")
    else:
        print("\n⚠️  WARNING: This will reorganize your data directory!")
        response = input("Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Migration cancelled.")
            return 0

    # Create backup first (unless skipped)
    if not args.skip_backup and not args.dry_run:
        create_backup(data_dir, dry_run=False)

    # Execute migration
    create_directory_structure(data_dir, args.dry_run)
    migrate_inputs(data_dir, args.dry_run)
    migrate_outputs(data_dir, args.dry_run)
    migrate_arcgis_exports(data_dir, args.dry_run)
    migrate_intermediate(data_dir, args.dry_run)

    if not args.dry_run:
        cleanup_old_structure(data_dir, dry_run=False)

    print("\n" + "="*80)
    print("MIGRATION COMPLETE!")
    print("="*80)

    if args.dry_run:
        print("\n✓ Dry run complete. Re-run without --dry-run to execute.")
    else:
        print("\n✓ Data directory reorganized successfully!")
        print("\nNext steps:")
        print("  1. Run: python scripts/update_config_paths.py")
        print("  2. Test pipeline: python src/main.py --run_name test")

    return 0


if __name__ == "__main__":
    exit(main())
