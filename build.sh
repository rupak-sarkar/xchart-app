#!/bin/bash
echo "Building xchart.in static site..."
mkdir -p dist

# Copy web files
cp *.html dist/ 2>/dev/null || true
cp *.js dist/ 2>/dev/null || true
cp *.json dist/ 2>/dev/null || true
cp *.css dist/ 2>/dev/null || true
cp *.ico dist/ 2>/dev/null || true
cp *.xml dist/ 2>/dev/null || true
cp *.txt dist/ 2>/dev/null || true
cp *.png dist/ 2>/dev/null || true
cp *.svg dist/ 2>/dev/null || true

# Copy data directories
cp -r screener_data dist/ 2>/dev/null || true
cp -r charts dist/ 2>/dev/null || true
cp -r output dist/ 2>/dev/null || true

echo "Files in dist/:"
ls dist/
echo ""
echo "Total size: $(du -sh dist/ | cut -f1)"
echo "Done!"
