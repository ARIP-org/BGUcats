import SwiftUI

/// Scan a cat, after "Send": "Which cat?", then the post. Both read and
/// change the flow kept beside the upload queue (`ScanFlow`), so a closed
/// app comes back to the same page. The words are the web app's
/// (`web/i18n/en.json`, `scan.*`), in English.

/// "Which cat?": every public cat (`GET /cats`), a search field, "Not
/// sure", and "A cat that isn't here" (not built yet: the new-cat form is
/// its own issue).
struct WhichCatPage: View {
    let world: World
    @ObservedObject var outbox: Outbox
    @State private var cats: [Cat] = []
    @State private var phase: Phase = .loading
    @State private var search = ""

    enum Phase: Equatable {
        case loading
        case loaded
        case failed(String)
    }

    var body: some View {
        List {
            Section {
                switch phase {
                case .loading:
                    ProgressView()
                        .frame(maxWidth: .infinity)
                case .failed(let why):
                    VStack(alignment: .leading, spacing: 8) {
                        Text(why)
                            .foregroundStyle(.secondary)
                        Button("Try again") {
                            Task { await load() }
                        }
                        .buttonStyle(.glass)
                    }
                case .loaded:
                    if shown.isEmpty {
                        Text(search.isEmpty ? "No campus cats yet." : "No cat called “\(search)”.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(shown) { cat in
                        Button {
                            choose(cat)
                        } label: {
                            CatRow(cat: cat, photos: world.photos, chosen: outbox.flow?.catId == cat.id)
                        }
                        .accessibilityIdentifier("cat.\(cat.id)")
                    }
                }
            } header: {
                Text("Campus cats")
            }
            Section {
                Button {
                    unsure()
                } label: {
                    Label("Not sure", systemImage: "questionmark.circle")
                        .foregroundStyle(.primary)
                }
                .accessibilityIdentifier("which.unsure")
                LabeledContent {
                    Text("Not built yet")
                } label: {
                    Label("A cat that isn't here", systemImage: "plus.circle")
                }
                .foregroundStyle(.secondary)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("which.new")
            }
        }
        .navigationTitle("Which cat?")
        .searchable(text: $search, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search cats")
        .task {
            if phase == .loading {
                await load()
            }
        }
    }

    private var shown: [Cat] {
        let words = search.trimmingCharacters(in: .whitespaces)
        guard !words.isEmpty else { return cats }
        return cats.filter { ($0.name ?? "").localizedCaseInsensitiveContains(words) }
    }

    private func load() async {
        phase = .loading
        do {
            cats = try await world.backend.cats()
            phase = .loaded
            world.trail.mark("scan: \(cats.count) cats listed")
        } catch {
            // A sign-in that ended is the session's to say.
            if (error as? ApiError)?.status == 401 { return }
            phase = .failed((error as? ApiError)?.message ?? "The cats could not be read. Try again.")
        }
    }

    private func choose(_ cat: Cat) {
        guard var flow = outbox.flow else { return }
        flow.catId = cat.id
        flow.catName = cat.name
        flow.unsure = false
        flow.step = .post
        outbox.keepFlow(flow)
        world.trail.mark("scan: cat chosen")
    }

    private func unsure() {
        guard var flow = outbox.flow else { return }
        flow.catId = nil
        flow.catName = nil
        flow.unsure = true
        flow.step = .post
        outbox.keepFlow(flow)
        world.trail.mark("scan: not sure")
    }
}

/// One cat in the list: its cover and its name.
private struct CatRow: View {
    let cat: Cat
    let photos: Photos
    let chosen: Bool

    var body: some View {
        HStack(spacing: 12) {
            PhotoView(url: cat.cover, photos: photos)
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .accessibilityHidden(true)
            Text(cat.name ?? "A cat with no name yet")
                .foregroundStyle(.primary)
            Spacer()
            if chosen {
                Image(systemName: "checkmark")
                    .foregroundStyle(.tint)
                    .accessibilityLabel("Chosen")
            }
        }
    }
}

/// The post: the cat said, the photos in their order, a few words, "Add
/// location", and "Post", which asks for the terms first and then queues
/// the pick and the post behind the photos.
struct PostPage: View {
    let world: World
    let session: Session
    @ObservedObject var outbox: Outbox
    @State private var text = ""
    @State private var shareRegion = true
    @State private var read = false
    @State private var posting = false
    @State private var note: String?

    var body: some View {
        Form {
            Section {
                HStack {
                    Label(catLine, systemImage: outbox.flow?.unsure == true ? "questionmark.circle" : "cat")
                    Spacer()
                    Button("Change") {
                        guard var flow = outbox.flow else { return }
                        flow.step = .which
                        outbox.keepFlow(flow)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityIdentifier("post.change")
                }
            }
            Section("Photos") {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 4), spacing: 6) {
                    ForEach(outbox.flow?.photos ?? [], id: \.id) { shot in
                        Tile(image: outbox.flowThumbs[shot.id], gallery: false)
                    }
                }
                .padding(.vertical, 4)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(photoCount)
                .accessibilityIdentifier("post.photos")
            }
            Section {
                TextField("What was the cat up to?", text: $text, axis: .vertical)
                    .lineLimit(3...6)
                    .accessibilityIdentifier("post.text")
            } header: {
                Text("Description · optional")
            } footer: {
                Text("\(text.count)/\(ScanFlow.textLimit)")
            }
            Section {
                Toggle(isOn: $shareRegion) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Add location")
                        Text(shareRegion ? "Friends see roughly where, never the exact spot" : "Off: the spot stays with you")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                .accessibilityIdentifier("post.region")
            }
        }
        .navigationTitle("New post")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Post") {
                    Task { await post() }
                }
                .disabled(posting || outbox.flow == nil)
                .accessibilityIdentifier("post.send")
            }
        }
        .alert("That did not work", isPresented: Binding(get: { note != nil }, set: { if !$0 { note = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(note ?? "")
        }
        .onAppear {
            guard !read, let flow = outbox.flow else { return }
            read = true
            text = flow.text
            shareRegion = flow.shareRegion
        }
        .onChange(of: text) { _, now in
            if now.count > ScanFlow.textLimit {
                text = String(now.prefix(ScanFlow.textLimit))
                return
            }
            keep()
        }
        .onChange(of: shareRegion) { _, _ in
            keep()
        }
    }

    private var catLine: String {
        guard let flow = outbox.flow else { return "" }
        if flow.unsure {
            return "Not sure which cat"
        }
        return "You met \(flow.catName ?? "a cat with no name yet")"
    }

    private var photoCount: String {
        let count = outbox.flow?.photos.count ?? 0
        return count == 1 ? "1 photo" : "\(count) photos"
    }

    /// What is written stays on the phone as it is typed.
    private func keep() {
        guard read, var flow = outbox.flow, flow.step == .post else { return }
        flow.text = text
        flow.shareRegion = shareRegion
        outbox.keepFlow(flow)
    }

    private func post() async {
        guard !posting, outbox.flow != nil else { return }
        posting = true
        defer { posting = false }
        // The terms before anything is sent: a "no" sends nothing.
        do {
            guard try await session.termsFirst() else { return }
        } catch {
            if (error as? ApiError)?.status == 401 { return }
            note = (error as? ApiError)?.message ?? "Try again."
            return
        }
        // The dialog may have been up a while: the flow as it is now.
        guard var flow = outbox.flow, flow.step == .post else { return }
        flow.text = String(text.prefix(ScanFlow.textLimit))
        flow.shareRegion = shareRegion
        // The post's id first, kept, so a tap after a crash is the same post.
        flow.postId = flow.postId ?? Ulid.make()
        outbox.keepFlow(flow)
        guard let writes = flow.writes() else { return }
        outbox.finish(encounterId: flow.encounterId, pick: writes.pick, post: writes.post)
        flow.step = .posted
        outbox.keepFlow(flow)
        world.trail.mark("scan: post queued\(writes.pick == nil ? ", no cat" : ", with its cat")")
    }
}
