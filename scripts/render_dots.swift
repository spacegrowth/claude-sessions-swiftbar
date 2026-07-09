#!/usr/bin/env swift
//
// Regenerates the base64 PNG icon constants in ccsessions/app.py:
//   LIVE_DOT_IMG, PARKED_DOT_IMG, DELETE_ICON_IMG
//
// Why PNGs and not `sfimage=` + `sfcolor=`?
//   SwiftBar builds the SF Symbol with the palette colour applied and then
//   unconditionally runs `image?.isTemplate = true` (MenuLineParameters.swift),
//   so AppKit re-tints the glyph with the menu's text colour and `sfcolor` is
//   silently discarded. `image=` decodes with isTemplate:false and keeps its
//   colour — the same mechanism that makes the CLAUDE_ICON crab render orange.
//
// Each icon is rendered at 32x32 px of data with a 16pt logical size, i.e. @2x,
// so it stays crisp on Retina without needing SwiftBar's width=/height= resize.
//
// Usage:  swift scripts/render_dots.swift
// Then paste the printed base64 into the matching constant in ccsessions/app.py.

import AppKit

// Keep these in sync with GREEN / PARKED_COLOR in ccsessions/app.py.
let icons: [(constant: String, symbol: String, hex: String)] = [
    ("LIVE_DOT_IMG",    "circle.inset.filled", "#34C759"),  // GREEN        — live
    ("PARKED_DOT_IMG",  "circle.dotted",       "#AEAEB2"),  // PARKED_COLOR — parked
    ("DELETE_ICON_IMG", "trash",               "#FF3B30"),  // destructive red
]

let pixels = 32          // bitmap data
let points: CGFloat = 16 // logical size  => @2x
let symbolPointSize: CGFloat = 13

func color(_ hex: String) -> NSColor {
    var s = hex
    if s.hasPrefix("#") { s.removeFirst() }
    var v: UInt64 = 0
    Scanner(string: s).scanHexInt64(&v)
    return NSColor(srgbRed: CGFloat((v >> 16) & 0xff) / 255,
                   green: CGFloat((v >> 8) & 0xff) / 255,
                   blue: CGFloat(v & 0xff) / 255, alpha: 1)
}

func render(symbol: String, hex: String) -> String? {
    guard let base = NSImage(systemSymbolName: symbol, accessibilityDescription: nil) else {
        FileHandle.standardError.write("MISSING SF Symbol: \(symbol)\n".data(using: .utf8)!)
        return nil
    }
    let cfg = NSImage.SymbolConfiguration(pointSize: symbolPointSize, weight: .regular)
    guard let sym = base.withSymbolConfiguration(cfg) else { return nil }

    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
    rep.size = NSSize(width: points, height: points)   // pts < px  =>  @2x backing

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let r = NSRect(x: (points - sym.size.width) / 2, y: (points - sym.size.height) / 2,
                   width: sym.size.width, height: sym.size.height)
    sym.draw(in: r)          // draw the (template) glyph
    color(hex).set()
    r.fill(using: .sourceAtop)  // tint only its opaque pixels
    NSGraphicsContext.restoreGraphicsState()

    return rep.representation(using: .png, properties: [:])?.base64EncodedString()
}

for icon in icons {
    guard let b64 = render(symbol: icon.symbol, hex: icon.hex) else { continue }
    print("\(icon.constant) = \"\(b64)\"")
    print("")
}
