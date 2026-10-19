// Subject lift with macOS Vision (the "lift subject from background" feature in Photos).
// Usage: klip-lift <input image> <output.png>. Writes the foreground subject(s) on a transparent
// background at the input's size. Exit 3 = no subject found. Built and cached by klip/cutout.py.
import CoreImage
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write("usage: klip-lift <in> <out.png>\n".data(using: .utf8)!)
    exit(2)
}
guard let image = CIImage(contentsOf: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("cannot read \(args[1])\n".data(using: .utf8)!)
    exit(2)
}
let request = VNGenerateForegroundInstanceMaskRequest()
let handler = VNImageRequestHandler(ciImage: image)
do {
    try handler.perform([request])
    guard let result = request.results?.first, !result.allInstances.isEmpty else { exit(3) }
    let buffer = try result.generateMaskedImage(ofInstances: result.allInstances, from: handler,
                                                croppedToInstancesExtent: false)
    let out = CIImage(cvPixelBuffer: buffer)
    try CIContext().writePNGRepresentation(of: out, to: URL(fileURLWithPath: args[2]), format: .RGBA8,
                                           colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)
    exit(1)
}
