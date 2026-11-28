import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// A profile photo, made ready on the phone as the web app makes it
/// (web/social/avatar.js; docs/app-plan/02-architecture.md, "Storage"): cut
/// to a centred square, turned upright, scaled to at most 512 px a side and
/// written as a new JPEG of at most 200 KB, the quality stepped down until
/// it fits. It is drawn anew, so nothing the camera wrote into the file
/// (where, when, with what) goes with it: the server refuses a picture that
/// still carries EXIF, XMP or IPTC (`jpeg_problem` in src/common/media.py),
/// and this file checks its own output the same way before it is sent.
/// Core Graphics and ImageIO only.
enum Avatar {
    /// The web app's `SIDE`, `MAX_BYTES` and `QUALITIES`, and the server's
    /// `AVATAR_MAX_BYTES` and `AVATAR_TYPE`. A Linux test holds them equal.
    static let side = 512
    static let maxBytes = 200_000
    static let qualities: [Double] = [0.86, 0.76, 0.66, 0.56, 0.46]
    static let type = "image/jpeg"
    /// The smallest side tried before giving up, as the web app.
    static let smallest = 128

    enum Failure: Error {
        /// Not a picture this phone can open.
        case unreadable
        /// No size and quality brought it under `maxBytes`.
        case tooLarge
    }

    /// A file as it came from the picker (any kind of picture the phone can
    /// open) -> the JPEG to upload.
    static func ready(_ file: Data) throws -> Data {
        guard
            let source = CGImageSourceCreateWithData(file as CFData, nil),
            CGImageSourceGetCount(source) > 0,
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
            let width = properties[kCGImagePropertyPixelWidth] as? Int,
            let height = properties[kCGImagePropertyPixelHeight] as? Int,
            min(width, height) > 0
        else { throw Failure.unreadable }
        // Read upright (the way the camera held it) and no larger than the
        // square needs: a 48-megapixel photo is never decoded whole. The
        // longer side is what this option limits, so it is the shorter
        // side's 512 times the picture's proportion.
        let long = max(width, height), short = min(width, height)
        let needed = short <= side ? long : Int((Double(side) * Double(long) / Double(short)).rounded(.up))
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: needed,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let upright = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            throw Failure.unreadable
        }
        return try ready(upright)
    }

    /// A picture already upright -> the JPEG to upload.
    static func ready(_ image: CGImage) throws -> Data {
        let cut = min(image.width, image.height)
        guard cut > 0, let square = image.cropping(to: CGRect(
            x: (image.width - cut) / 2, y: (image.height - cut) / 2, width: cut, height: cut
        )) else { throw Failure.unreadable }
        var edge = min(side, cut)
        while edge >= smallest {
            guard let drawn = draw(square, side: edge) else { throw Failure.unreadable }
            for quality in qualities {
                if let jpeg = encode(drawn, quality: quality), jpeg.count <= maxBytes, problem(jpeg) == nil {
                    return jpeg
                }
            }
            edge = Int((Double(edge) * 0.75).rounded())
        }
        throw Failure.tooLarge
    }

    /// The square drawn anew at `side` pixels, opaque, in sRGB.
    private static func draw(_ square: CGImage, side: Int) -> CGImage? {
        guard
            let space = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: 0,
                space: space, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
            )
        else { return nil }
        context.interpolationQuality = .high
        context.draw(square, in: CGRect(x: 0, y: 0, width: side, height: side))
        return context.makeImage()
    }

    /// A JPEG with nothing in it but the picture: ImageIO is given no
    /// properties but the quality, and whatever it writes of its own in
    /// APP1 or APP13 is taken out (`stripped`).
    private static func encode(_ image: CGImage, quality: Double) -> Data? {
        let out = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return stripped(out as Data)
    }

    /// The JPEG segments the server refuses (`_METADATA_MARKERS`): APP1 is
    /// EXIF and XMP, APP13 is IPTC.
    static let metadata: [UInt8: String] = [0xE1: "EXIF or XMP", 0xED: "IPTC"]

    /// The file without its APP1 and APP13 segments; everything else, the
    /// picture's own data included, as it was.
    static func stripped(_ jpeg: Data) -> Data {
        let bytes = [UInt8](jpeg)
        guard bytes.count > 4, bytes[0] == 0xFF, bytes[1] == 0xD8 else { return jpeg }
        var out: [UInt8] = [0xFF, 0xD8]
        var at = 2
        while at + 4 <= bytes.count {
            guard bytes[at] == 0xFF else { return jpeg }
            let marker = bytes[at + 1]
            if marker == 0xFF {
                at += 1
                continue
            }
            if marker == 0xDA {
                // The picture's own data: kept to the end.
                out += bytes[at...]
                return Data(out)
            }
            let end = at + 2 + (Int(bytes[at + 2]) << 8 | Int(bytes[at + 3]))
            guard end <= bytes.count else { return jpeg }
            if metadata[marker] == nil {
                out += bytes[at..<end]
            }
            at = end
        }
        return jpeg
    }

    /// What the server would refuse in this file, or nil: the same walk as
    /// `jpeg_problem` in src/common/media.py, over the whole file.
    static func problem(_ jpeg: Data) -> String? {
        let bytes = [UInt8](jpeg)
        guard bytes.count >= 3, bytes[0] == 0xFF, bytes[1] == 0xD8, bytes[2] == 0xFF else {
            return "not a JPEG picture"
        }
        var at = 2
        while at + 4 <= bytes.count {
            guard bytes[at] == 0xFF else { return "not a JPEG picture" }
            let marker = bytes[at + 1]
            if marker == 0xFF {
                at += 1
                continue
            }
            if marker == 0xDA {
                return nil
            }
            if let what = metadata[marker] {
                return "it still carries \(what) data"
            }
            at += 2 + (Int(bytes[at + 2]) << 8 | Int(bytes[at + 3]))
        }
        return nil
    }

    /// A picture's size in pixels as a file says it, for the stand-in
    /// server's record.
    static func pixels(_ file: Data) -> (width: Int, height: Int)? {
        guard
            let source = CGImageSourceCreateWithData(file as CFData, nil),
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
            let width = properties[kCGImagePropertyPixelWidth] as? Int,
            let height = properties[kCGImagePropertyPixelHeight] as? Int
        else { return nil }
        return (width, height)
    }
}
