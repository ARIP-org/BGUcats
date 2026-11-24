import ImageIO
import PhotosUI
import SwiftUI
import UIKit

/// "Scan a cat", its first half: take photos or choose them from the
/// gallery, see them, and send them as one encounter (the upload queue,
/// Outbox.swift). Choosing the cat and posting are the second half, not
/// built yet.
struct ScanView: View {
    let world: World
    @ObservedObject private var outbox: Outbox
    @State private var chosen: [Chosen] = []
    @State private var picked: [PhotosPickerItem] = []
    @State private var camera = false
    /// Photos from the gallery being read, or the chosen ones being kept.
    @State private var working = false
    @State private var note: String?
    /// The stand-in camera's count, so each drawn photo differs.
    @State private var drawn = 0

    init(world: World) {
        self.world = world
        _outbox = ObservedObject(wrappedValue: world.outbox)
    }

    var body: some View {
        NavigationStack {
            Group {
                if !outbox.batch.isEmpty {
                    sending
                } else if chosen.isEmpty {
                    empty
                } else {
                    choosing
                }
            }
            .navigationTitle("Scan a cat")
            .alert("That did not work", isPresented: noteShown) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(note ?? "")
            }
        }
        // The place is asked for while this screen is open: a camera photo
        // carries the latest fix, and nothing waits for one.
        .onAppear { world.places.start() }
        .onDisappear { world.places.stop() }
        .fullScreenCover(isPresented: $camera) {
            CameraView(took: { image in took(image) }, close: { camera = false })
                .ignoresSafeArea()
        }
        .onChange(of: picked) { _, items in
            Task { await read(items) }
        }
    }

    private var noteShown: Binding<Bool> {
        Binding(get: { note != nil }, set: { shown in
            if !shown {
                note = nil
            }
        })
    }

    // ------------------------------------------------------------ choosing

    private var empty: some View {
        ContentUnavailableView {
            Label("Photos of one cat", systemImage: "camera")
        } description: {
            Text("Take photos of one cat, or choose them from the gallery. They are sent together, as one encounter.")
        } actions: {
            takeButton
                .buttonStyle(.glassProminent)
            galleryButton
                .buttonStyle(.glass)
            if working {
                ProgressView()
            }
        }
    }

    private var choosing: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                LazyVGrid(columns: ScanView.columns, spacing: 8) {
                    ForEach(Array(chosen.enumerated()), id: \.element.id) { number, photo in
                        Tile(image: photo.thumb, gallery: photo.gallery)
                            .overlay(alignment: .topTrailing) {
                                Button {
                                    chosen.removeAll { $0.id == photo.id }
                                    world.trail.mark("scan: removed a photo")
                                } label: {
                                    Image(systemName: "xmark")
                                }
                                .buttonStyle(.glass)
                                .buttonBorderShape(.circle)
                                .controlSize(.small)
                                .padding(4)
                                .accessibilityLabel("Remove")
                                .accessibilityIdentifier("scan.remove.\(number + 1)")
                            }
                    }
                }
                Text(chosen.count == 1 ? "1 photo" : "\(chosen.count) photos")
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("scan.count")
                VStack(alignment: .leading) {
                    takeButton
                    galleryButton
                }
                .buttonStyle(.glass)
                if working {
                    ProgressView()
                }
                Button {
                    send()
                } label: {
                    Label("Send", systemImage: "paperplane")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                .controlSize(.large)
                .disabled(working)
                .accessibilityIdentifier("scan.send")
            }
            .padding()
        }
    }

    @ViewBuilder private var takeButton: some View {
        Button {
            if world.drawn {
                drawn += 1
                took(DrawnPhotos.draw("camera \(drawn)"))
            } else {
                camera = true
            }
        } label: {
            Label("Take a photo", systemImage: "camera")
        }
        .disabled(!world.drawn && !UIImagePickerController.isSourceTypeAvailable(.camera))
        .accessibilityIdentifier("scan.take")
    }

    /// The system's picker: it needs no permission, and the app sees only
    /// the photos chosen.
    @ViewBuilder private var galleryButton: some View {
        if world.drawn {
            Button {
                // The stand-in gallery hands out two drawn photos.
                for word in ["gallery 1", "gallery 2"] {
                    let image = DrawnPhotos.draw(word)
                    if let made = Pictures.chosen(image: image, gallery: true, capturedAt: nil, place: nil) {
                        chosen.append(made)
                    }
                }
                world.trail.mark("scan: chose 2 from the gallery")
            } label: {
                Label("Choose from the gallery", systemImage: "photo.on.rectangle")
            }
            .accessibilityIdentifier("scan.gallery")
        } else {
            PhotosPicker(selection: $picked, matching: .images) {
                Label("Choose from the gallery", systemImage: "photo.on.rectangle")
            }
            .accessibilityIdentifier("scan.gallery")
        }
    }

    /// A photo from the camera, with where the phone is now if it knows.
    private func took(_ image: UIImage) {
        let place = world.places.fix
        let at = world.now()
        working = true
        Task {
            let made = await Task.detached(priority: .userInitiated) {
                Pictures.chosen(image: image, gallery: false, capturedAt: at, place: place)
            }.value
            working = false
            if let made {
                chosen.append(made)
                world.trail.mark("scan: took a photo\(place == nil ? ", no place yet" : "")")
            } else {
                note = "The photo could not be made into a JPEG. Take it again."
            }
        }
    }

    private func read(_ items: [PhotosPickerItem]) async {
        guard !items.isEmpty else { return }
        picked = []
        working = true
        defer { working = false }
        var refused = 0
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self) else {
                refused += 1
                continue
            }
            let made = await Task.detached(priority: .userInitiated) {
                Pictures.fromGallery(data)
            }.value
            if let made {
                chosen.append(made)
            } else {
                refused += 1
            }
        }
        world.trail.mark("scan: chose \(items.count - refused) from the gallery")
        if refused > 0 {
            note = refused == 1
                ? "One photo could not be read. It may be a video, or not on this phone yet."
                : "\(refused) photos could not be read. They may be videos, or not on this phone yet."
        }
    }

    private func send() {
        let photos = chosen
        working = true
        Task {
            defer { working = false }
            do {
                try await world.outbox.send(photos, lateFix: world.places.fix)
                chosen = []
                world.trail.mark("scan: sent \(photos.count) photos")
            } catch {
                world.trail.mark("scan: not kept (\(Auth.kind(error)))")
                note = "The photos could not be kept on this phone, so nothing was sent. Is its storage full?"
            }
        }
    }

    // ------------------------------------------------------------ sending

    private var sending: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                LazyVGrid(columns: ScanView.columns, spacing: 8) {
                    ForEach(outbox.batch) { shown in
                        VStack(spacing: 6) {
                            Tile(image: shown.thumb, gallery: shown.gallery)
                                .overlay(alignment: .topTrailing) {
                                    StateMark(state: outbox.states[shown.id])
                                        .padding(6)
                                }
                            ProgressView(value: fraction(outbox.states[shown.id]))
                                .accessibilityHidden(true)
                        }
                    }
                }
                notes
            }
            .padding()
        }
    }

    @ViewBuilder private var header: some View {
        let total = outbox.batch.count
        let sent = outbox.sentCount
        if outbox.busy {
            Text("\(sent) of \(total) sent")
                .font(.title2.bold())
                .accessibilityIdentifier("scan.progress")
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Text(sent == total ? "Sent: \(total == 1 ? "1 photo" : "\(total) photos")" : "Sent: \(sent) of \(total) photos")
                    .font(.title2.bold())
                    .accessibilityIdentifier("scan.sent")
                Text("Choosing the cat and posting are not built yet in this app. The app on the home screen has them.")
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// Why a photo is waiting, in words: one line per reason.
    @ViewBuilder private var notes: some View {
        let retrying = reasons { if case .retrying(let why) = $0 { return why } else { return nil } }
        let failed = reasons { if case .failed(let why) = $0 { return why } else { return nil } }
        ForEach(retrying, id: \.why) { reason in
            Label {
                Text("\(reason.count == 1 ? "One photo" : "\(reason.count) photos") did not go. \(reason.why) The others are not held up.")
            } icon: {
                Image(systemName: "arrow.clockwise")
            }
            .foregroundStyle(.orange)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("scan.retrying")
        }
        ForEach(failed, id: \.why) { reason in
            Label {
                Text("\(reason.count == 1 ? "One photo" : "\(reason.count) photos") could not be sent: \(reason.why)")
            } icon: {
                Image(systemName: "exclamationmark.triangle")
            }
            .foregroundStyle(.red)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("scan.failed")
        }
        if !outbox.busy {
            if outbox.failedCount > 0 {
                Button("Try again") {
                    outbox.retryFailed()
                }
                .buttonStyle(.glass)
            }
            Button {
                outbox.clear()
                chosen = []
            } label: {
                Label("Scan another cat", systemImage: "camera")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.glassProminent)
            .controlSize(.large)
            .accessibilityIdentifier("scan.another")
        }
    }

    private struct Reason {
        let why: String
        let count: Int
    }

    private func reasons(_ pick: (Outbox.State) -> String?) -> [Reason] {
        var order: [String] = []
        var counts: [String: Int] = [:]
        for shown in outbox.batch {
            guard let state = outbox.states[shown.id], let why = pick(state) else { continue }
            if counts[why] == nil {
                order.append(why)
            }
            counts[why, default: 0] += 1
        }
        return order.map { Reason(why: $0, count: counts[$0] ?? 0) }
    }

    private func fraction(_ state: Outbox.State?) -> Double {
        switch state {
        case .sending(let value): return 0.1 + 0.85 * value
        case .sent: return 1
        default: return 0
        }
    }

    private static let columns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 3)
}

/// One photo, square, with "from the gallery" on it when it is.
private struct Tile: View {
    let image: UIImage?
    let gallery: Bool

    var body: some View {
        Color(.secondarySystemFill)
            .aspectRatio(1, contentMode: .fit)
            .overlay {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    ProgressView()
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(alignment: .bottomLeading) {
                if gallery {
                    Text("from the gallery")
                        .font(.caption2.weight(.medium))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(.regularMaterial, in: Capsule())
                        .padding(6)
                        .accessibilityIdentifier("scan.mark.gallery")
                }
            }
    }
}

/// A photo's state, as a sign in its corner.
private struct StateMark: View {
    let state: Outbox.State?

    var body: some View {
        switch state {
        case .sent:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.white, .green)
                .accessibilityLabel("Sent")
        case .retrying:
            Image(systemName: "arrow.clockwise.circle.fill")
                .foregroundStyle(.white, .orange)
                .accessibilityLabel("Trying again")
        case .failed:
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.white, .red)
                .accessibilityLabel("Not sent")
        default:
            EmptyView()
        }
    }
}

/// The system's camera. iOS asks for it the first time, with the sentence
/// in the project's Info.plist keys.
private struct CameraView: UIViewControllerRepresentable {
    let took: (UIImage) -> Void
    let close: () -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        private let parent: CameraView

        init(_ parent: CameraView) {
            self.parent = parent
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage {
                parent.took(image)
            }
            parent.close()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.close()
        }
    }
}

/// Making what was taken or chosen into what the API takes: a JPEG of 20
/// MB at most, upright.
enum Pictures {
    static let limit = 20 * 1024 * 1024

    /// A photo from the gallery, in whatever format it is (HEIC, PNG, ...).
    /// It is drawn again as a JPEG, which also leaves the file's own place
    /// (its EXIF) behind: a gallery photo carries no place at all. When it
    /// was taken is read first and sent apart.
    static func fromGallery(_ data: Data) -> Chosen? {
        guard let image = UIImage(data: data) else { return nil }
        return chosen(image: image, gallery: true, capturedAt: takenAt(data), place: nil)
    }

    static func chosen(image: UIImage, gallery: Bool, capturedAt: Date?, place: Fix?) -> Chosen? {
        guard let jpeg = jpeg(image) else { return nil }
        return Chosen(
            id: ULID.make(),
            jpeg: jpeg,
            thumb: Shrink.thumb(image),
            gallery: gallery,
            capturedAt: capturedAt,
            place: gallery ? nil : place
        )
    }

    static func jpeg(_ image: UIImage) -> Data? {
        var picture = upright(image)
        for _ in 0..<3 {
            for quality in [0.9, 0.75, 0.6] {
                if let data = picture.jpegData(compressionQuality: quality), data.count <= limit {
                    return data
                }
            }
            // Still too large: smaller, and again.
            picture = scaled(picture, by: 0.7)
        }
        return nil
    }

    /// The pixels the right way up, so nothing after depends on a flag.
    private static func upright(_ image: UIImage) -> UIImage {
        guard image.imageOrientation != .up else { return image }
        return scaled(image, by: 1)
    }

    private static func scaled(_ image: UIImage, by factor: CGFloat) -> UIImage {
        let size = CGSize(width: (image.size.width * factor).rounded(), height: (image.size.height * factor).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }

    /// When the photo was taken, from its EXIF, in the phone's own zone.
    static func takenAt(_ data: Data) -> Date? {
        guard
            let source = CGImageSourceCreateWithData(data as CFData, nil),
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
            let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any],
            let original = exif[kCGImagePropertyExifDateTimeOriginal] as? String
        else { return nil }
        let reader = DateFormatter()
        reader.locale = Locale(identifier: "en_US_POSIX")
        reader.timeZone = .current
        reader.dateFormat = "yyyy:MM:dd HH:mm:ss"
        return reader.date(from: original)
    }
}
