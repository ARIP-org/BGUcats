import ImageIO
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Where a picture comes from.
protocol Photos {
    func image(_ url: URL) async -> UIImage?
}

/// The network, with what was read kept in memory. A photo's address is
/// signed anew in every answer; the photo behind it is the same, so it is
/// kept under the address without its signature.
final class NetPhotos: Photos {
    private let kept = NSCache<NSString, UIImage>()

    func image(_ url: URL) async -> UIImage? {
        let key = ((url.host ?? "") + url.path) as NSString
        if let hit = kept.object(forKey: key) {
            return hit
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        guard let (data, response) = try? await URLSession.shared.data(for: request) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200, let image = UIImage(data: data) else { return nil }
        kept.setObject(image, forKey: key)
        return image
    }
}

/// For UI tests: a picture drawn from the address's last word, the same
/// one every time, neither light nor dark. No network.
final class DrawnPhotos: Photos {
    func image(_ url: URL) async -> UIImage? {
        DrawnPhotos.draw(url.lastPathComponent)
    }

    /// The picture for a word. The Scan screen's stand-in camera and
    /// gallery hand these out too.
    static func draw(_ word: String) -> UIImage {
        let seed = word.unicodeScalars.reduce(0) { $0 + Int($1.value) * 5 }
        let hue = CGFloat(seed % 12) / 12
        let size = CGSize(width: 400, height: 400)
        return UIGraphicsImageRenderer(size: size).image { context in
            UIColor(hue: hue, saturation: 0.45, brightness: 0.55, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: size))
            UIColor(hue: hue, saturation: 0.5, brightness: 0.42, alpha: 1).setFill()
            context.cgContext.fillEllipse(in: CGRect(x: 110, y: 130, width: 180, height: 160))
        }
    }

    /// A file as a camera writes it, for the profile photo under UI tests
    /// (the simulator has no picker to drive): a drawn picture, wider than
    /// it is tall and larger than a profile photo, in a JPEG that carries
    /// made-up EXIF, TIFF and GPS (a camera, a time, a place on campus),
    /// so that the walk shows what is sent has none of it.
    static func cameraFile(_ word: String) -> Data? {
        let seed = word.unicodeScalars.reduce(0) { $0 + Int($1.value) * 7 }
        let hue = CGFloat(seed % 12) / 12
        let size = CGSize(width: 1200, height: 900)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let image = UIGraphicsImageRenderer(size: size, format: format).image { context in
            UIColor(hue: hue, saturation: 0.4, brightness: 0.6, alpha: 1).setFill()
            context.fill(CGRect(origin: .zero, size: size))
            UIColor(hue: hue, saturation: 0.55, brightness: 0.4, alpha: 1).setFill()
            context.cgContext.fillEllipse(in: CGRect(x: 380, y: 230, width: 440, height: 440))
        }
        guard let picture = image.cgImage else { return nil }
        let out = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        let madeUp: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: 0.9,
            kCGImagePropertyTIFFDictionary: [
                kCGImagePropertyTIFFMake: "Made-up camera",
                kCGImagePropertyTIFFModel: "Stand-in 1",
            ] as [CFString: Any],
            kCGImagePropertyExifDictionary: [
                kCGImagePropertyExifDateTimeOriginal: "2026:11:28 09:30:00",
                kCGImagePropertyExifLensModel: "Made-up lens",
            ] as [CFString: Any],
            kCGImagePropertyGPSDictionary: [
                kCGImagePropertyGPSLatitude: 31.2622,
                kCGImagePropertyGPSLatitudeRef: "N",
                kCGImagePropertyGPSLongitude: 34.8013,
                kCGImagePropertyGPSLongitudeRef: "E",
            ] as [CFString: Any],
        ]
        CGImageDestinationAddImage(destination, picture, madeUp as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return out as Data
    }
}

/// One picture, filling whatever space it is given. While it loads, a
/// spinner; if it cannot be read, a sign that says so.
struct PhotoView: View {
    let url: URL?
    let photos: Photos
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Color(.secondarySystemFill)
            .overlay {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else if failed {
                    Image(systemName: "photo")
                        .foregroundStyle(.secondary)
                } else {
                    ProgressView()
                }
            }
            .clipped()
            .task(id: url) {
                guard let url else {
                    failed = true
                    return
                }
                if let loaded = await photos.image(url) {
                    image = loaded
                    failed = false
                } else {
                    failed = true
                }
            }
    }
}

/// A person's round picture, or the first letter of their name.
struct AvatarView: View {
    let person: Person
    let photos: Photos
    var size: CGFloat = 36

    var body: some View {
        Group {
            if let url = person.avatar {
                PhotoView(url: url, photos: photos)
            } else {
                Color(.tertiarySystemFill)
                    .overlay {
                        Text(String(person.displayName.prefix(1)).uppercased())
                            .font(.system(size: size * 0.45, weight: .semibold))
                            .foregroundStyle(.secondary)
                    }
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .accessibilityHidden(true)
    }
}
