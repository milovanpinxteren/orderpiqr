/**
 * PWA Icon & Splash Screen Generator for Orderpiqr
 *
 * Run: npm install sharp
 * Then: node scripts/generate-pwa-icons.js
 */

const fs = require('fs');
const path = require('path');

let sharp;
try {
  sharp = require('sharp');
} catch (e) {
  console.log('Sharp is not installed. Run: npm install sharp');
  process.exit(1);
}

const sourceIcon = path.join(__dirname, '..', 'orderpiqrApp', 'static', 'icons', 'icon-512.png');
const outputDir = path.join(__dirname, '..', 'orderpiqrApp', 'static', 'icons');

const icons = [
  { name: 'apple-touch-icon.png', size: 180 },
  { name: 'apple-touch-icon-152.png', size: 152 },
  { name: 'apple-touch-icon-167.png', size: 167 },
  { name: 'apple-touch-icon-180.png', size: 180 },
];

// iOS splash screens: centered logo on white (#f4f6f9) background
const splashScreens = [
  // iPhone SE (3rd gen)
  { name: 'splash-750x1334.png', width: 750, height: 1334 },
  // iPhone 8 Plus
  { name: 'splash-1242x2208.png', width: 1242, height: 2208 },
  // iPhone X / XS / 11 Pro
  { name: 'splash-1125x2436.png', width: 1125, height: 2436 },
  // iPhone XR / 11
  { name: 'splash-828x1792.png', width: 828, height: 1792 },
  // iPhone XS Max / 11 Pro Max
  { name: 'splash-1242x2688.png', width: 1242, height: 2688 },
  // iPhone 12/13/14
  { name: 'splash-1170x2532.png', width: 1170, height: 2532 },
  // iPhone 12/13/14 Pro Max
  { name: 'splash-1284x2778.png', width: 1284, height: 2778 },
  // iPhone 14 Pro
  { name: 'splash-1179x2556.png', width: 1179, height: 2556 },
  // iPhone 14 Pro Max / 15 Plus
  { name: 'splash-1290x2796.png', width: 1290, height: 2796 },
  // iPhone 15 Pro
  { name: 'splash-1179x2556.png', width: 1179, height: 2556 },
  // iPad (10th gen) / iPad Air
  { name: 'splash-1640x2360.png', width: 1640, height: 2360 },
  // iPad Pro 11"
  { name: 'splash-1668x2388.png', width: 1668, height: 2388 },
  // iPad Pro 12.9"
  { name: 'splash-2048x2732.png', width: 2048, height: 2732 },
];

// Deduplicate by name
const uniqueSplash = [...new Map(splashScreens.map(s => [s.name, s])).values()];

const BG = { r: 244, g: 246, b: 249, alpha: 1 }; // #f4f6f9

async function generateIcons() {
  console.log('Generating Apple touch icons...\n');

  for (const icon of icons) {
    const outputPath = path.join(outputDir, icon.name);
    try {
      await sharp(sourceIcon)
        .resize(icon.size, icon.size)
        .png()
        .toFile(outputPath);
      console.log(`  Generated: ${icon.name}`);
    } catch (err) {
      console.error(`  Failed ${icon.name}:`, err.message);
    }
  }

  console.log('\nGenerating iOS splash screens...\n');

  for (const splash of uniqueSplash) {
    const outputPath = path.join(outputDir, splash.name);
    try {
      const logoSize = Math.round(Math.min(splash.width, splash.height) * 0.3);

      const logo = await sharp(sourceIcon)
        .resize(logoSize, logoSize)
        .png()
        .toBuffer();

      await sharp({
        create: {
          width: splash.width,
          height: splash.height,
          channels: 4,
          background: BG,
        }
      })
        .composite([{ input: logo, gravity: 'center' }])
        .png()
        .toFile(outputPath);

      console.log(`  Generated: ${splash.name}`);
    } catch (err) {
      console.error(`  Failed ${splash.name}:`, err.message);
    }
  }

  console.log('\nDone! Icons saved to orderpiqrApp/static/icons/');
}

generateIcons().catch(console.error);
