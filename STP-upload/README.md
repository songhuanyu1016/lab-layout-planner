# STP Upload Folder

Drop `.stp` or `.step` files here and push to trigger automatic conversion.

## How to add a new component to the library:

1. Add your `.stp` file to this folder
2. Commit and push to `main`
3. GitHub Actions will automatically:
   - Convert the STP file to a `.comp.json` component
   - Add it to the `Library/` folder
   - Update the library index
   - Remove the STP file (to keep the repo small)
4. The component will appear in the web planner within a few minutes

## Notes
- File name becomes the component name (e.g., `My Laser.stp` → `My Laser.comp.json`)
- Conversion uses tolerance=5.0 and assumes mm units
- Large STP files (>50MB) may take several minutes to convert
