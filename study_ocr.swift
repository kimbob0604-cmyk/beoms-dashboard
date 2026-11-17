import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
let inDir = args[1], outDir = args[2]
let fm = FileManager.default
let files = try! fm.contentsOfDirectory(atPath: inDir).filter { $0.hasSuffix(".jpeg") || $0.hasSuffix(".jpg") }.sorted()
for f in files {
  let stem = (f as NSString).deletingPathExtension
  let out = "\(outDir)/\(stem).json"
  if fm.fileExists(atPath: out) { continue }
  guard let img = NSImage(contentsOfFile: "\(inDir)/\(f)"),
        let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("skip \(f)"); continue }
  let req = VNRecognizeTextRequest()
  req.recognitionLevel = .accurate
  req.recognitionLanguages = ["ko-KR", "en-US"]
  req.usesLanguageCorrection = true
  let h = VNImageRequestHandler(cgImage: cg, options: [:])
  try? h.perform([req])
  var lines: [[String: Any]] = []
  for o in req.results ?? [] {
    guard let c = o.topCandidates(1).first else { continue }
    let b = o.boundingBox
    lines.append(["t": c.string, "c": Double(c.confidence),
                  "x": Double(b.minX), "y": Double(1 - b.maxY), "w": Double(b.width), "h": Double(b.height)])
  }
  let obj: [String: Any] = ["w": cg.width, "h": cg.height, "lines": lines]
  let d = try! JSONSerialization.data(withJSONObject: obj, options: [])
  try! d.write(to: URL(fileURLWithPath: out))
  print("ok \(stem) \(lines.count)")
}
