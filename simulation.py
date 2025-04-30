from typing import Union
from sqlmodel import SQLModel, Session, create_engine, select
import random
import simpy
from faker import Faker
import utilities
import models
import os


# Set a random seed for reproducibility
fake = Faker()
random.seed(42)
Faker.seed(42)

# === Global Variables ===
NUMBER_OF_PRACTITIONERS = 5
INITIAL_NUMBER_OF_PATIENTS = 10 * NUMBER_OF_PRACTITIONERS

# Define the simulation duration in minutes
# Currently: 12 * 4 weeks (ca. 3 * 4 months) in minutes
SIMULATION_DURATION = 60 * 24 * 7 * 12 * 4  

# Define appointment/encounter durations
VISIT_DURATIONS = [15, 30, 45, 60]
VISIT_DURATION = lambda: random.choice(VISIT_DURATIONS)

# Appointment related probabilities
CANCEL_PROBABILITY = 0.1
NOSHOW_PROBABILITY = 0.1

# Pobability related to the chance of generating observations
# during an encounter
OBSERVATIONS_DURING_ENCOUNTER_PROBABILITY = 0.5

# Probability of Break The Glass events
BTG_PROBABILITY = 0.025
STANDALONE_BTG_PROBABILITY = 0.0125

# Probability of patient not re-queueing for a next appointment
DISCHARGE_PROBABILITY = 0.05

# Cooldown duration between appointents books
PATIENT_COOLDOWN = 60 * 24  # 24 * 7 hours in minutes (adjust as needed)
last_patient_activity = {}  # Tracks last activity time for each patient

# Track currently active/on-going appointments
active_appointments: set[tuple[str, str]] = (
    set()
)  # Tuples of (patient_id, practitioner.name)

# Patient population related probabilities
DISCHARGE_PROBABILITY = 0.05  # 5% chance patient leaves after each sequence
NEW_PATIENT_PROBABILITY = 0.1  # 10% chance to add new patients each cycle
TARGET_POPULATION = INITIAL_NUMBER_OF_PATIENTS
MIN_POPULATION = int(TARGET_POPULATION * 0.7)  # Threshold for adding new patients


def find_next_available_time(
    requested_time: int,
    practitioner_object: models.Practitioner,
    appointment_duration: int,
    lookahead_minutes: int = 7 * 24 * 60,
):
    """Find next available slot by querying all scheduled events from database"""
    with Session(engine) as session:
        # Get all non-cancelled appointments for this practitioner (including
        # NOSHOW)
        appointments = session.exec(
            select(models.Appointment)
            .where(models.Appointment.practitioner_id == practitioner_object.id)
            .where(
                (models.Appointment.status == models.AppointmentStatus.BOOKED)
                | (models.Appointment.status == models.AppointmentStatus.NOSHOW)
            )
        ).all()

        # Get all encounters for this practitioner
        encounters = session.exec(
            select(models.Encounter).where(
                models.Encounter.practitioner_id == practitioner_object.id
            )
        ).all()

        # Get all observations for this practitioner
        observations = session.exec(
            select(models.Observation).where(
                models.Observation.practitioner_id == practitioner_object.id
            )
        ).all()

        # Convert all events to time slots for overlap checking
        booked_slots = [
            (x.scheduled_start_time, x.scheduled_start_time + x.duration)
            for x in appointments
        ]

        encounter_slots = [
            (x.actual_start_time, x.actual_start_time + x.duration) for x in encounters
        ]

        observation_slots = [
            # Assuming observations take 1 minute
            (x.timestamp, x.timestamp + 1)
            for x in observations
        ]

        # Combine all slots that could cause conflicts
        all_busy_slots = booked_slots + encounter_slots + observation_slots

        for t in range(requested_time, requested_time + lookahead_minutes):
            day = (t // (24 * 60)) % 7
            minute_of_day = t % (24 * 60)

            if practitioner_object._work_schedule is not None:
                for start, end in practitioner_object._work_schedule.get(day, []):
                    # Check if slot fits in working hours
                    if start <= minute_of_day <= end - appointment_duration:
                        # Check for overlaps with all existing events
                        slot_start = t
                        slot_end = t + appointment_duration
                        overlap = any(
                            existing_start < slot_end and existing_end > slot_start
                            for existing_start, existing_end in all_busy_slots
                        )
                        if not overlap:
                            return t
            else:
                raise ValueError("Practitioner has no work schedule defined")
    return None


def is_time_available(
    environment,
    practitioner_object: models.Practitioner,
    start_time: int,
    duration: int = 1,
) -> bool:
    """Check if a practitioner has any conflicts during the specified time period"""
    end_time = start_time + duration

    with Session(engine) as session:
        # Check appointments
        conflicting_appointments = session.exec(
            select(models.Appointment)
            .where(models.Appointment.practitioner_id == practitioner_object.id)
            .where(models.Appointment.status == models.AppointmentStatus.BOOKED)
            .where(models.Appointment.scheduled_start_time < end_time)
            .where(
                models.Appointment.scheduled_start_time + models.Appointment.duration
                > start_time
            )
        ).first()

        if conflicting_appointments:
            return False

        # Check encounters
        conflicting_encounters = session.exec(
            select(models.Encounter)
            .where(models.Encounter.practitioner_id == practitioner_object.id)
            .where(models.Encounter.actual_start_time < end_time)
            .where(
                models.Encounter.actual_start_time + models.Encounter.duration
                > start_time
            )
        ).first()

        if conflicting_encounters:
            return False

        # Check observations
        conflicting_observations = session.exec(
            select(models.Observation)
            .where(models.Observation.practitioner_id == practitioner_object.id)
            .where(models.Observation.timestamp >= start_time)
            .where(models.Observation.timestamp < end_time)
        ).first()

        if conflicting_observations:
            return False

    # Also check if within working hours
    day = (start_time // (24 * 60)) % 7
    minute_of_day = start_time % (24 * 60)

    if practitioner_object._work_schedule is None:
        raise ValueError("Practitioner has no work schedule defined")

    for work_start, work_end in practitioner_object._work_schedule.get(day, []):
        if work_start <= minute_of_day <= work_end - duration:
            return True

    return False


def appointment(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
):
    appointment_duration = VISIT_DURATION()
    key = (patient_object.id, practitioner_object.id)

    requested_time = environment.now
    # Step 1: Search for a future time slot
    scheduled_start_time = find_next_available_time(
        requested_time, practitioner_object, appointment_duration
    )

    if scheduled_start_time is None:
        print(
            f"[{environment.now:>4}] No available time found for {patient_object.id} with {practitioner_object.id}"
        )
        return None

    # Step 2: Reserve the slot by logging the scheduled appointment
    appointment_id = fhir_logger.log_appointment(
        patient_id=patient_object.id,
        created=environment.now,
        status=models.AppointmentStatus.BOOKED,
        practitioner_id=practitioner_object.id,
        duration=appointment_duration,
        scheduled_start_time=scheduled_start_time,
    )

    print(
        f"[{environment.now:>4}] {patient_object.id} scheduled with {practitioner_object.id} at {scheduled_start_time} for {appointment_duration} min"
    )

    # Step 3: Simulate potential cancellation before appointment
    total_wait_time = int(scheduled_start_time - environment.now)
    cancellation_check_time = 0
    if total_wait_time > 0:

        # Step 3.1: Random cancellation in between now and the scheduled appointment time
        cancellation_check_time = random.randint(0, total_wait_time)
        # Use the 'timeout' function to simulate the passage of time
        yield environment.timeout(cancellation_check_time)

        # Step 3.2: Check to see if we should cancel the appointment at this time
        if random.random() < CANCEL_PROBABILITY:
            fhir_logger.update_appointment_status(
                appointment_id=appointment_id,
                new_status=models.AppointmentStatus.CANCELLED,
                recorded=environment.now,
                practitioner_id=practitioner_object.id,
                reason="Patient cancelled",
            )
            print(
                f"[{environment.now:>4}] {patient_object.id} CANCELLED appointment with {practitioner_object.id}"
            )
            return None

    # 3.3 The appointment was not cancelled, so wait the remaining time until the scheduled appointment
    remaining_wait_time = total_wait_time - cancellation_check_time
    yield environment.timeout(remaining_wait_time)

    # Step 4: Show up or no-show
    if random.random() < NOSHOW_PROBABILITY:
        # Mark as no-show
        fhir_logger.update_appointment_status(
            appointment_id=appointment_id,
            new_status=models.AppointmentStatus.NOSHOW,
            recorded=environment.now,
            practitioner_id=practitioner_object.id,
        )
        print(
            f"[{environment.now:>4}] {patient_object.id} NO-SHOW for appointment with {practitioner_object.id}"
        )
        return None

    # Step 5: Attend appointment
    with practitioner_object.resource.request() as request:
        yield request
        active_appointments.add(key)

        print(
            f"[{environment.now:>4}] {practitioner_object.id} starts APPOINTMENT with {patient_object.id} ({appointment_duration} min)"
        )

        # The appointment progresses in the form of an Encounter
        main_process = environment.process(
            encounter(
                environment=environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
                appointment_id=appointment_id,
                appointment_start=scheduled_start_time,
                appointment_duration=appointment_duration,
            )
        )

        # Add potential BTG event during appointment
        if random.random() < BTG_PROBABILITY:
            btg_proc = environment.process(
                btg_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    context_resource_type="Appointment",
                    context_resource_id=appointment_id,
                )
            )
            # Run both processes in parallel
            yield main_process | btg_proc
        else:
            yield main_process

        active_appointments.discard(key)

        fhir_logger.update_appointment_status(
            appointment_id=appointment_id,
            new_status=models.AppointmentStatus.FINISHED,
            recorded=environment.now,
            practitioner_id=practitioner_object.id,
        )


def encounter(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
    appointment_id: str,
    appointment_start: int,
    appointment_duration: int,
):
    """Simulates an encounter inside the timeframe of the appointment."""
    print(
        f"[{environment.now:>4}] {practitioner_object.id} begins ENCOUNTER with {patient_object.id}"
    )

    # Calculate encounter duration
    encounter_duration = max(
        min(VISIT_DURATIONS),
        random.randint(appointment_duration // 2, appointment_duration),
    )

    # Calculate maximum possible start delay
    max_delay = appointment_duration - encounter_duration
    start_delay = random.randint(0, max_delay)

    # Calculate actual start and end times
    encounter_start = appointment_start + start_delay
    encounter_end = encounter_start + encounter_duration

    main_process = environment.timeout(encounter_duration)

    # Log the encounter between the patient and practitioner
    encounter_id = fhir_logger.log_encounter(
        patient_id=patient_object.id,
        actual_start_time=encounter_start,
        # actual_start_time=appointment_start,
        duration=encounter_duration,
        practitioner_id=practitioner_object.id,
        appointment_id=appointment_id,
    )

    # Add potential BTG event during encounter
    if random.random() < BTG_PROBABILITY:
        btg_proc = environment.process(
            btg_process(
                environment=environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
                context_resource_type="Encounter",
                context_resource_id=encounter_id,
            )
        )
        yield main_process | btg_proc
    else:
        yield main_process

    if random.random() < OBSERVATIONS_DURING_ENCOUNTER_PROBABILITY:
        yield environment.process(
            observations(
                environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
                encounter_start=encounter_start,
                # encounter_start=appointment_start,
                duration=appointment_duration,
                encounter_id=encounter_id,
            )
        )


def observations(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
    encounter_start: int,
    duration: int,
    encounter_id: str,
):
    """Simulates an observation recorded inside the timeframe of the encounter."""
    count = random.randint(1, 5)
    observation_codes = {
        0: ("8310-5", "Body Temperature"),
        1: ("8867-4", "Heart Rate"),
        2: ("9279-1", "Respiratory Rate"),
        3: ("8480-6", "Blood Pressure"),
        4: ("2345-7", "Blood Glucose"),
    }

    for i in range(count):
        obs_time = encounter_start + random.randint(0, duration)
        code, display = observation_codes[i % 5]
        value = (
            f"{random.uniform(96, 99):.1f} °F"
            if i == 0
            else str(random.randint(60, 100))
        )
        print(f"[{obs_time:>4}] Observation {i+1} for patient {patient_object.id}")

        obs_id = fhir_logger.log_observation(
            patient_id=patient_object.id,
            practitioner_id=practitioner_object.id,
            timestamp=obs_time,
            code=code,
            value=value,
            encounter_id=encounter_id,
        )

        # Add potential BTG event during observation
        if random.random() < BTG_PROBABILITY:
            yield environment.process(
                btg_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    context_resource_type="Observation",
                    context_resource_id=obs_id,
                )
            )

        yield environment.timeout(0)


def btg_process(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
    context_resource_type: Union[str, None] = None,
    context_resource_id: Union[str, None] = None,
):
    """Simulates a Break The Glass event"""
    # Random delay before BTG event occurs
    delay = random.randint(0, 10)
    yield environment.timeout(delay)

    # Determine purpose based on context
    purpose = "emergency-access"
    if context_resource_type:
        purpose_of_event = f"Emergency access during {context_resource_type}"
    else:
        purpose_of_event = "Emergency access - standalone event"

    # Log the BTG event
    fhir_logger.log_break_the_glass(
        patient_id=patient_object.id,
        recorded=environment.now,
        practitioner_id=practitioner_object.id,
        action="access",
        purpose=purpose,
        purpose_of_event=purpose_of_event,
        target_resource_type=context_resource_type,
        target_resource_id=context_resource_id,
        outcome="success",
    )

    print(
        f"[{environment.now:>4}] BTG EVENT by {practitioner_object.id} for {patient_object.id}"
        f"{f' during {context_resource_type}' if context_resource_type else ''}"
    )


def standalone_btg_event_generator(
    environment, fhir_logger, practitioner_objects, patient_objects
):
    """Independent process that generates standalone BTG events with probability control"""
    while True:
        # Wait random interval (1-24 hours in simulation minutes)
        yield environment.timeout(random.randint(60, 60 * 24))

        # Only proceed with probability STANDALONE_BTG_PROBABILITY
        if random.random() < STANDALONE_BTG_PROBABILITY:
            # Randomly select practitioner and patient
            practitioner = random.choice(practitioner_objects)
            patient = random.choice(patient_objects)

            # Trigger BTG event
            environment.process(
                btg_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner,
                    patient_object=patient,
                )
            )


# === Patient Process ===
def patient_process(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
):
    """Simulates a patient triggering events according to probability rules."""
    # An event sequence can start with one of the following events
    event_type = random.choices(
        population=[
            "Appointment",
            "Encounter",
            "Observation",
        ],
        weights=[0.75, 0.20, 0.05],
        k=1,
    )[0]

    if event_type == "Appointment":
        yield environment.process(
            appointment(
                environment=environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
            )
        )
    elif event_type == "Encounter":
        encounter_duration = VISIT_DURATION()
        current_time = environment.now

        # Check if time is available right now
        if is_time_available(
            environment, practitioner_object, current_time, encounter_duration
        ):
            yield environment.process(
                encounter(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    appointment_start=current_time,
                    appointment_duration=encounter_duration,
                    appointment_id=None,
                )
            )
        else:
            print(f"[{current_time:>4}] Could not start encounter - practitioner busy")
    elif event_type == "Observation":
        current_time = environment.now

        # Observations are quick (1 minute), just check exact time
        if is_time_available(environment, practitioner_object, current_time):
            yield environment.process(
                observations(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    encounter_start=current_time,
                    duration=1,
                    encounter_id=None,
                )
            )
        else:
            print(
                f"[{current_time:>4}] Could not record observation - practitioner busy"
            )


def fill_patient_queue(environment, patient_queue, patient_objects: list, interval=15):
    for patient_object in patient_objects:
        arrival_time = int(random.expovariate(1.0 / interval))
        yield environment.timeout(arrival_time)
        patient_queue.put(patient_object)


# === Scheduler ===
def scheduler(
    engine,
    environment,
    fhir_logger,
    patient_queue,
    practitioner_objects,
    patient_objects,
):
    # Initialize tracking
    active_patient_count = len(patient_objects)
    print(f"[{environment.now:>4}] Starting with {active_patient_count} patients")

    # Initialize last activity times
    # global last_patient_activity
    # last_patient_activity = {p.id: environment.now for p in patient_objects}

    # Initial queue filling
    environment.process(fill_patient_queue(environment, patient_queue, patient_objects))

    while True:
        # Population maintenance
        if active_patient_count < MIN_POPULATION or (
            random.random() < NEW_PATIENT_PROBABILITY
            and active_patient_count < TARGET_POPULATION
        ):

            new_patients_needed = min(3, TARGET_POPULATION - active_patient_count)
            new_patients = [create_patient(engine) for _ in range(new_patients_needed)]

            # Initialize activity times for new patients
            # for p in new_patients:
            #     last_patient_activity[p.id] = environment.now

            environment.process(
                fill_patient_queue(environment, patient_queue, new_patients)
            )
            active_patient_count += new_patients_needed
            print(
                f"[{environment.now:>4}] Added {new_patients_needed} new patients (Total: {active_patient_count})"
            )

        # Get next patient
        patient_object = yield patient_queue.get()
        current_time = environment.now

        # Check cooldown period if patient was recently active
        if patient_object.id in last_patient_activity:
            time_since_last = current_time - last_patient_activity[patient_object.id]
            if time_since_last < PATIENT_COOLDOWN:
                # Skip this patient for now, put back in queue with remaining cooldown
                remaining_cooldown = PATIENT_COOLDOWN - time_since_last
                yield environment.timeout(remaining_cooldown)
                patient_queue.put(patient_object)
                continue

        # Process patient with available practitioner
        practitioner_object = random.choice(practitioner_objects)
        main_process = environment.process(
            patient_process(
                environment, fhir_logger, practitioner_object, patient_object
            )
        )
        yield main_process

        # Update last activity time
        last_patient_activity[patient_object.id] = environment.now

        # Determine patient disposition
        if random.random() < DISCHARGE_PROBABILITY:
            # Patient discharged - remove from tracking
            if patient_object.id in last_patient_activity:
                del last_patient_activity[patient_object.id]
            active_patient_count -= 1
            print(
                f"[{environment.now:>4}] Patient {patient_object.id[:8]} discharged (Remaining: {active_patient_count})"
            )
        else:
            # yield environment.timeout(PATIENT_COOLDOWN)
            # Patient continues - requeue immediately (cooldown enforced on next pull)
            patient_queue.put(patient_object)
            # print(
            #     f"[{environment.now:>4}] Patient {patient_object.id[:8]} re-queued after full cooldown"
            # )
            print(
                f"[{environment.now:>4}] Patient {patient_object.id[:8]} re-queued (eligible after cooldown)"
            )


def create_patient(engine):
    patient = models.Patient(
        id=fake.uuid4(),
        first_name=fake.first_name(),
        last_name=fake.last_name(),
        gender=fake.random_element(elements=["male", "female"]),
        birthdate=fake.date_of_birth(),
    )
    # Save the patient to the database
    with Session(engine) as session:
        session.add(patient)
        session.commit()
        session.refresh(patient)
    return patient


def create_practitioner(engine, environment, role="doctor"):
    if role == "doctor":
        practitioner = models.Practitioner(
            env=environment,
            # Assign a work schedule to the practitioner
            work_schedule=utilities.sample_practitioner_work_schedule(),
            # Fill in the remaining SQLModel fields
            id=fake.uuid4(),
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            gender=fake.random_element(elements=["male", "female"]),
            birthdate=fake.date_of_birth(),
            role=role,
        )
        # Save the pracitioner to the database
        with Session(engine) as session:
            session.add(practitioner)
            session.commit()
            session.refresh(practitioner)
        return practitioner
    else:
        raise ValueError


# === Main ===
def run_simulation(engine, pracitioners: int, patients: int):

    # === Simulation Setup ===
    environment = simpy.Environment()
    patient_queue = simpy.Store(environment)

    # Create patients
    patient_objects = [create_patient(engine) for _ in range(patients)]
    practitioner_objects = [
        create_practitioner(engine, environment) for _ in range(pracitioners)
    ]

    provenance_tracker = models.ProvenanceTracker(engine=engine)

    # Mechanism for logging events
    fhir_logger = models.FHIRLogger(
        engine=engine, provenance_tracker=provenance_tracker
    )

    # Launch scheduler
    environment.process(
        scheduler(
            engine=engine,
            environment=environment,
            fhir_logger=fhir_logger,
            patient_queue=patient_queue,
            practitioner_objects=practitioner_objects,
            patient_objects=patient_objects,
        )
    )

    environment.process(
        standalone_btg_event_generator(
            environment, fhir_logger, practitioner_objects, patient_objects
        )
    )

    # Run simulation
    environment.run(until=SIMULATION_DURATION)


# Run it
if __name__ == "__main__":
    db_filename = "hospital_simulation.db"

    if os.path.exists(db_filename):
        os.remove(db_filename)
    # Database setup
    engine = create_engine(f"sqlite:///{db_filename}")

    # Create tables
    SQLModel.metadata.create_all(engine)

    # Simulation start: env.now = 0 → Monday at 00:00 (midnight)
    run_simulation(
        engine=engine,
        pracitioners=NUMBER_OF_PRACTITIONERS,
        patients=INITIAL_NUMBER_OF_PATIENTS,
    )
    print("TOTAL - SIM_DURATION: ", SIMULATION_DURATION)
