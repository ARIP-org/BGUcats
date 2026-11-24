import CoreLocation
import Foundation

/// Where the phone is, as a photo carries it: rounded to three decimals
/// (about 100 m) on the phone already, with the accuracy the phone gave.
struct Fix: Codable, Equatable {
    let lat: Double
    let lon: Double
    let accuracyM: Double

    init(lat: Double, lon: Double, accuracyM: Double) {
        self.lat = (lat * 1000).rounded() / 1000
        self.lon = (lon * 1000).rounded() / 1000
        self.accuracyM = accuracyM.rounded()
    }
}

/// The phone's place at the moment of a photo. Nothing waits for it: a
/// photo taken before the first fix has none.
protocol Places: AnyObject {
    /// Asks for the place (the first time, iOS asks the person) and listens.
    func start()
    func stop()
    /// The latest fix, if one arrived in the last two minutes.
    var fix: Fix? { get }
}

final class DevicePlaces: NSObject, Places, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var latest: CLLocation?
    private var listening = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
    }

    func start() {
        listening = true
        switch manager.authorizationStatus {
        case .notDetermined:
            // iOS asks, with the sentence in the project's Info.plist keys.
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            manager.startUpdatingLocation()
        default:
            // Refused: photos go without a place.
            break
        }
    }

    func stop() {
        listening = false
        manager.stopUpdatingLocation()
    }

    var fix: Fix? {
        guard let latest, latest.horizontalAccuracy >= 0, -latest.timestamp.timeIntervalSinceNow < 120 else {
            return nil
        }
        return Fix(lat: latest.coordinate.latitude, lon: latest.coordinate.longitude, accuracyM: latest.horizontalAccuracy)
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let allowed = [.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus)
        if listening && allowed {
            manager.startUpdatingLocation()
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        latest = locations.last
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // No fix: the next photo goes without a place. Nothing to say.
    }
}

/// For UI tests: a made-up place, known at once. No GPS, no question.
final class StandInPlaces: Places {
    private var started = false

    func start() {
        started = true
    }

    func stop() {}

    var fix: Fix? {
        started ? Fix(lat: 31.262, lon: 34.801, accuracyM: 12) : nil
    }
}
