import SwiftUI

/// Why a thing is reported: the server's fixed list
/// (`src/common/reports.py`, `REASONS`), in the order the web app shows it,
/// with the web app's words (`report.reason.*` in `web/i18n/en.json`).
enum ReportReason: String, CaseIterable, Identifiable {
    case spam
    case offensive
    case harassment
    case privacy
    case notCat = "not_cat"
    case other

    var id: String { rawValue }

    var words: String {
        switch self {
        case .spam: "Spam or advertising"
        case .offensive: "Offensive, hateful or sexual"
        case .harassment: "Harassment or bullying"
        case .privacy: "Shows a person or private details"
        case .notCat: "Not about a campus cat"
        case .other: "Something else"
        }
    }
}

/// Reporting a post: a reason from the list and, if the person wants, a
/// line of their own. The answer is always the same, so the sheet says
/// thank you and nothing else: nobody learns what others reported.
struct ReportView: View {
    let post: Post
    let world: World
    @Environment(\.dismiss) private var dismiss

    /// Made once, when the sheet opens: sending again is the same report.
    @State private var reportId = Ulid.make()
    @State private var reason: ReportReason?
    @State private var note = ""
    @State private var sending = false
    @State private var sent = false
    @State private var failure: String?

    static let noteLimit = 280

    var body: some View {
        NavigationStack {
            Group {
                if sent {
                    thanks
                } else {
                    form
                }
            }
            .navigationTitle("Report \(post.author.displayName)'s post")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if sent {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                            .accessibilityIdentifier("report.done")
                    }
                } else {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { dismiss() }
                            .accessibilityIdentifier("report.cancel")
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        if sending {
                            ProgressView()
                        } else {
                            Button("Send report") {
                                Task { await send() }
                            }
                            .disabled(reason == nil)
                            .accessibilityIdentifier("report.send")
                        }
                    }
                }
            }
        }
    }

    private var form: some View {
        Form {
            Section {
                ForEach(ReportReason.allCases) { each in
                    Button {
                        reason = each
                    } label: {
                        HStack {
                            Text(each.words)
                                .foregroundStyle(Color.primary)
                            Spacer()
                            if reason == each {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(Color.accentColor)
                            }
                        }
                    }
                    .accessibilityIdentifier("reason.\(each.rawValue)")
                    .accessibilityAddTraits(reason == each ? .isSelected : [])
                }
            } header: {
                Text("What is wrong")
            } footer: {
                Text("Tell us what is wrong. They are not told who reported.")
            }

            Section {
                TextField("Anything to add? (optional)", text: $note, axis: .vertical)
                    .lineLimit(2...5)
                    .onChange(of: note) { _, now in
                        if now.count > ReportView.noteLimit {
                            note = String(now.prefix(ReportView.noteLimit))
                        }
                    }
                    .accessibilityIdentifier("report.note")
            }

            if let failure {
                Section {
                    Label(failure, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                }
            }
        }
        .disabled(sending)
    }

    private var thanks: some View {
        ContentUnavailableView {
            Label("Thank you", systemImage: "checkmark.circle")
        } description: {
            Text("Someone looks at every report within a day.")
                .accessibilityIdentifier("report.thanks")
        }
    }

    private func send() async {
        guard let reason, !sending else { return }
        sending = true
        failure = nil
        defer { sending = false }
        let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            try await world.backend.report(Report(
                reportId: reportId,
                targetType: "post",
                targetId: post.id,
                reason: reason,
                note: trimmed.isEmpty ? nil : trimmed
            ))
            world.trail.mark("report: sent (\(reason.rawValue))")
            sent = true
        } catch {
            let status = (error as? ApiError)?.status ?? 0
            world.trail.mark("report: failed (\(status))")
            if status == 401 {
                // The session puts the sign-in screen up.
                dismiss()
                return
            }
            failure = (error as? ApiError)?.message ?? "Try again."
        }
    }
}
