import SwiftUI

/// Scan a cat, after "Send": "Which cat?", the new-cat form, then the
/// post. Each reads and changes the flow kept beside the upload queue
/// (`ScanFlow`), so a closed app comes back to the same page. The words are
/// the web app's (`web/i18n/en.json`, `scan.*`), in English.

/// "Which cat?": every public cat (`GET /cats`), a search field, "Not
/// sure", and "A cat that isn't here", which opens the new-cat form.
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
                Button {
                    newCat()
                } label: {
                    Label("A cat that isn't here", systemImage: "plus.circle")
                        .foregroundStyle(.primary)
                }
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
        flow.proposal = nil
        flow.proposalId = nil
        flow.step = .post
        outbox.keepFlow(flow)
        world.trail.mark("scan: cat chosen")
    }

    private func unsure() {
        guard var flow = outbox.flow else { return }
        flow.catId = nil
        flow.catName = nil
        flow.unsure = true
        flow.proposal = nil
        flow.proposalId = nil
        flow.step = .post
        outbox.keepFlow(flow)
        world.trail.mark("scan: not sure")
    }

    /// The form, with what was answered there before if it was.
    private func newCat() {
        guard var flow = outbox.flow else { return }
        flow.catId = nil
        flow.catName = nil
        flow.unsure = false
        flow.proposal = flow.proposal ?? ScanFlow.Proposal()
        flow.step = .new
        outbox.keepFlow(flow)
        world.trail.mark("scan: new cat")
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

/// The encounter's photos, small, in the order they were taken.
private struct FlowShots: View {
    @ObservedObject var outbox: Outbox
    let id: String

    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 4), spacing: 6) {
            ForEach(outbox.flow?.photos ?? [], id: \.id) { shot in
                Tile(image: outbox.flowThumbs[shot.id], gallery: false)
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(count)
        .accessibilityIdentifier(id)
    }

    private var count: String {
        let count = outbox.flow?.photos.count ?? 0
        return count == 1 ? "1 photo" : "\(count) photos"
    }
}

/// "A cat that isn't here": the encounter's photos, a name idea, the coat,
/// where it hangs out, anything else, and two ways out. "Just add" asks for
/// the terms and queues the proposal behind the photos, with no post; "Add
/// & post" goes on to the post, which queues the proposal and the post.
/// Every answer is kept on the phone as it is given.
struct NewCatPage: View {
    let world: World
    let session: Session
    @ObservedObject var outbox: Outbox
    @State private var adding = false
    @State private var note: String?

    var body: some View {
        Form {
            Section("Photos") {
                FlowShots(outbox: outbox, id: "new.photos")
            }
            Section {
                TextField("e.g. Hummus", text: nameIdea)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .accessibilityIdentifier("new.name")
            } header: {
                Text("Name idea · optional")
            }
            Section {
                Picker("Coat", selection: coat) {
                    Text("Not said").tag(String?.none)
                    ForEach(Campus.coats) { choice in
                        Text(choice.name).tag(Optional(choice.id))
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("new.coat")
                Picker("Where does it hang out?", selection: region) {
                    Text("Not said").tag(String?.none)
                    ForEach(Campus.places + [Campus.elsewhere]) { choice in
                        Text(choice.name).tag(Optional(choice.id))
                    }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("new.where")
            }
            Section {
                ForEach(Campus.traits) { trait in
                    let chosen = outbox.flow?.proposal?.traits.contains(trait.id) == true
                    Button {
                        toggle(trait.id)
                    } label: {
                        HStack {
                            Text(trait.name)
                                .foregroundStyle(.primary)
                            Spacer()
                            if chosen {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(.tint)
                                    .accessibilityHidden(true)
                            }
                        }
                    }
                    .accessibilityValue(chosen ? "chosen" : "not chosen")
                    .accessibilityIdentifier("new.trait.\(trait.id)")
                }
            } header: {
                Text("Anything else?")
            } footer: {
                Text("An admin looks at every new cat before anyone else sees it.")
            }
        }
        .navigationTitle("New cat")
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 12) {
                Button {
                    Task { await add() }
                } label: {
                    Text("Just add")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glass)
                .accessibilityIdentifier("new.add")
                Button {
                    toPost()
                } label: {
                    Text("Add & post")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.glassProminent)
                .accessibilityIdentifier("new.post")
            }
            .controlSize(.large)
            .disabled(adding || outbox.flow?.proposal == nil)
            .padding(.horizontal)
            .padding(.bottom, 8)
        }
        .alert("That did not work", isPresented: Binding(get: { note != nil }, set: { if !$0 { note = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(note ?? "")
        }
    }

    private var nameIdea: Binding<String> {
        Binding(get: { outbox.flow?.proposal?.nameIdea ?? "" }, set: { now in
            change { $0.nameIdea = ScanFlow.cut(now, to: ScanFlow.nameLimit) }
        })
    }

    private var coat: Binding<String?> {
        Binding(get: { outbox.flow?.proposal?.coat }, set: { now in
            change { $0.coat = now }
        })
    }

    private var region: Binding<String?> {
        Binding(get: { outbox.flow?.proposal?.regionId }, set: { now in
            change { $0.regionId = now }
        })
    }

    private func toggle(_ trait: String) {
        change { proposal in
            if proposal.traits.contains(trait) {
                proposal.traits.removeAll { $0 == trait }
            } else {
                // In the server's order, as it keeps them.
                let chosen = Set(proposal.traits + [trait])
                proposal.traits = Campus.traits.map(\.id).filter { chosen.contains($0) }
            }
        }
    }

    /// An answer changed, kept at once.
    private func change(_ edit: (inout ScanFlow.Proposal) -> Void) {
        guard var flow = outbox.flow, flow.step == .new, var proposal = flow.proposal else { return }
        edit(&proposal)
        guard proposal != flow.proposal else { return }
        flow.proposal = proposal
        outbox.keepFlow(flow)
    }

    /// "Add & post": the post page, which sends the proposal with the post.
    private func toPost() {
        guard var flow = outbox.flow, flow.step == .new, flow.proposal != nil else { return }
        flow.step = .post
        outbox.keepFlow(flow)
        world.trail.mark("scan: new cat, to the post")
    }

    /// "Just add": the terms first (a proposal is written for the campus),
    /// then the proposal alone, behind the photos.
    private func add() async {
        guard !adding, outbox.flow?.proposal != nil else { return }
        adding = true
        defer { adding = false }
        do {
            guard try await session.termsFirst() else { return }
        } catch {
            if (error as? ApiError)?.status == 401 { return }
            note = (error as? ApiError)?.message ?? "Try again."
            return
        }
        // The dialog may have been up a while: the flow as it is now.
        guard var flow = outbox.flow, flow.step == .new, flow.proposal != nil else { return }
        // The proposal's id first, kept, so a tap after a crash is the same
        // proposal. No post: one made before is not this ending's.
        flow.proposalId = flow.proposalId ?? Ulid.make()
        flow.postId = nil
        outbox.keepFlow(flow)
        guard let writes = flow.writes(), let proposal = writes.proposal else { return }
        outbox.finish(encounterId: flow.encounterId, pick: nil, proposal: proposal, post: nil)
        flow.step = .added
        outbox.keepFlow(flow)
        world.trail.mark("scan: new cat added, no post")
    }
}

/// The post: the cat said, the photos in their order, a few words, "Add
/// location", and "Post", which asks for the terms first and then queues
/// the pick (or the new cat's proposal) and the post behind the photos.
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
                    Label(catLine, systemImage: catIcon)
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
                FlowShots(outbox: outbox, id: "post.photos")
            }
            Section {
                TextField("What was the cat up to?", text: $text, axis: .vertical)
                    .lineLimit(3...6)
                    .accessibilityIdentifier("post.text")
            } header: {
                Text("Description · optional")
            } footer: {
                Text("\(ScanFlow.length(text))/\(ScanFlow.textLimit)")
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
            if ScanFlow.length(now) > ScanFlow.textLimit {
                text = ScanFlow.cut(now)
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
        if let proposal = flow.proposal {
            // Named by its name idea, or "New cat".
            return proposal.name.map { "New cat: \($0)" } ?? "New cat"
        }
        return "You met \(flow.catName ?? "a cat with no name yet")"
    }

    private var catIcon: String {
        if outbox.flow?.unsure == true {
            return "questionmark.circle"
        }
        return outbox.flow?.proposal != nil ? "plus.circle" : "cat"
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
        flow.text = ScanFlow.cut(text)
        flow.shareRegion = shareRegion
        // The post's id first, and a new cat's, kept, so a tap after a crash
        // is the same post and the same proposal.
        flow.postId = flow.postId ?? Ulid.make()
        if flow.proposal != nil {
            flow.proposalId = flow.proposalId ?? Ulid.make()
        }
        outbox.keepFlow(flow)
        guard let writes = flow.writes(), let made = writes.post else { return }
        outbox.finish(encounterId: flow.encounterId, pick: writes.pick, proposal: writes.proposal, post: made)
        flow.step = .posted
        outbox.keepFlow(flow)
        let claim = writes.proposal != nil ? ", a new cat" : writes.pick == nil ? ", no cat" : ", with its cat"
        world.trail.mark("scan: post queued\(claim)")
    }
}
