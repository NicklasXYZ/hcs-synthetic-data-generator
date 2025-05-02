from typing import Union
from sqlmodel import SQLModel, Session, create_engine, select
import random
import simpy
from faker import Faker
import utilities
import models
import os

# import numpy as np

# Use Faker for the generation of user data
fake = Faker()

# Set a random seed for reproducibility
Faker.seed(42)
random.seed(42)

# === Simulation Configuration ===

# Duration of the simulation in months and minutes
SIMULATION_DURATION_IN_MONTHS = 12 * 4
SIMULATION_DURATION_IN_MINUTES = 60 * 24 * 7 * 4 * SIMULATION_DURATION_IN_MONTHS

# Number of practitioners and patients in the simulation
NUMBER_OF_PRACTITIONERS = 10
NUMBER_OF_PATIENTS = 500 * NUMBER_OF_PRACTITIONERS

# === Event Configuration ===

# Event types and their respective weights
EVENT_TYPE_WEIGHTS = {
    "Appointment": 0.75,
    "Encounter": 0.20,
    "Observation": 0.05,
}

# === Appointment Configuration ===

# Possible durations for appointments and encounters
APPOINTMENT_VISIT_DURATIONS = [15, 30, 45, 60]
APPOINTMENT_VISIT_DURATION = lambda: random.choice(APPOINTMENT_VISIT_DURATIONS)

# Probabilities related to appointments
APPOINTMENT_CANCEL_PROBABILITY = 0.10
APPOINTMENT_NOSHOW_PROBABILITY = 0.10

# === Observation Configuration ===

# Probability of generating observations during an encounter
OBSERVATIONS_DURING_ENCOUNTER_PROBABILITY = 0.50

# Observation codes and their descriptions
OBSERVATION_CODES = {
    0: ("8310-5", "Body Temperature"),
    1: ("8867-4", "Heart Rate"),
    2: ("9279-1", "Respiratory Rate"),
    3: ("8480-6", "Blood Pressure"),
    4: ("2345-7", "Blood Glucose"),
}
OBSERVATIONS_MAX = 5

# === Access Event Configuration ===

# Probabilities of normal and Break The Glass (BTG) access events
BTG_ACCESS_PROBABILITY = 0.025
STANDALONE_BTG_ACCESS_PROBABILITY = 0.0125
STANDALONE_NORMAL_ACCESS_PROBABILITY = 0.0125

# === Patient Scheduling Configuration ===

# Cooldown duration between appointment bookings
# Wait 3 days before trying to schedule the next appointment
# PATIENT_SCHEDULING_COOLDOWN_IN_DAYS = 3
# PATIENT_SCHEDULING_COOLDOWN_IN_MINUTES = 60 * 24 * PATIENT_SCHEDULING_COOLDOWN_IN_DAYS

# Define the average number of days between appointments
lambda_1 = 1  # Frequent visits (1-7 days between)
lambda_2 = 7
lambda_3 = 31 * 3  # Regular visits (3-6 months between)
lambda_4 = 31 * 6


# Function to generate cooldown duration using Poisson distribution
def sample_cooldown_time():
    if random.random() < 0.25:
        # Add 1 to ensure at least 1 day of cooldown
        # return np.random.poisson(lambda_2) + 1
        return random.randint(lambda_1, lambda_2)
    else:
        # Add 1 to ensure at least 1 day of cooldown
        # return np.random.poisson(lambda_1) + 1
        return random.randint(lambda_3, lambda_4)


# Cooldown duration between appointment bookings
PATIENT_SCHEDULING_COOLDOWN_IN_DAYS = lambda: sample_cooldown_time()
PATIENT_SCHEDULING_COOLDOWN_IN_MINUTES = (
    lambda: 60 * 24 * PATIENT_SCHEDULING_COOLDOWN_IN_DAYS()
)

# Track last activity time for each patient
last_patient_activity: dict = {}

# Track currently active/ongoing appointments
# Tuples of (patient_id, practitioner.id)
active_appointments: set[tuple[str, str]] = set()

# === Patient Population Configuration ===

# Probabilities related to patient population dynamics
# 10% chance patient leaves after each cycle
PATIENT_DISCHARGE_PROBABILITY = 0.10
# 10% chance to add new patients each cycle
PATIENT_ADMITTANCE_PROBABILITY = 0.10

# Target and minimum patient population
PATIENT_TARGET_POPULATION = NUMBER_OF_PATIENTS
PATIENT_MIN_POPULATION = int(PATIENT_TARGET_POPULATION * 0.75)


def find_next_available_time(
    engine,
    requested_time: int,
    practitioner_object: models.Practitioner,
    appointment_duration: int,
) -> int:
    """Efficiently find next available slot using gap search"""

    def fetch_busy_slots(session: Session) -> list[tuple[int, int]]:
        """Fetch all busy slots sorted by start time"""
        search_window_end = requested_time + 7 * 24 * 60  # look 7 days ahead

        appointments = session.exec(
            select(models.Appointment)
            .where(models.Appointment.practitioner_id == practitioner_object.id)
            .where(
                (
                    models.Appointment.status.in_(
                        [
                            models.AppointmentStatus.BOOKED,
                            models.AppointmentStatus.NOSHOW,
                        ]
                    )
                )
                & (models.Appointment.scheduled_start_time < search_window_end)
                & (
                    (
                        models.Appointment.scheduled_start_time
                        + models.Appointment.duration
                    )
                    > requested_time
                )
            )
        ).all()

        encounters = session.exec(
            select(models.Encounter).where(
                (models.Encounter.practitioner_id == practitioner_object.id)
                & (models.Encounter.actual_start_time < search_window_end)
                & (
                    (models.Encounter.actual_start_time + models.Encounter.duration)
                    > requested_time
                )
            )
        ).all()

        observations = session.exec(
            select(models.Observation).where(
                (models.Observation.practitioner_id == practitioner_object.id)
                & (models.Observation.timestamp < search_window_end)
                & ((models.Observation.timestamp + 1) > requested_time)
            )
        ).all()

        # Build list of (start, end) tuples
        booked_slots = [
            (x.scheduled_start_time, x.scheduled_start_time + x.duration)
            for x in appointments
        ]
        encounter_slots = [
            (x.actual_start_time, x.actual_start_time + x.duration) for x in encounters
        ]
        observation_slots = [(x.timestamp, x.timestamp + 1) for x in observations]

        all_slots = booked_slots + encounter_slots + observation_slots
        # Sort booked timeslots by start time
        return sorted(all_slots, key=lambda x: x[0])

    def is_within_working_hours(t_start: int, t_end: int) -> bool:
        """Check if time slot is within practitioner's working schedule"""
        day = (t_start // (24 * 60)) % 7
        minute_of_day_start = t_start % (24 * 60)
        minute_of_day_end = t_end % (24 * 60)

        if practitioner_object._work_schedule is None:
            raise ValueError("No work schedule defined for practitioner!")

        for work_start, work_end in practitioner_object._work_schedule.get(day, []):
            if work_start <= minute_of_day_start and minute_of_day_end <= work_end:
                return True
        return False

    with Session(engine) as session:
        busy_slots = fetch_busy_slots(session)

        # Start by assuming time is available starting from requested_time
        current_time = max(requested_time, 0)

        # Scan through gaps between busy slots
        for slot_start, slot_end in busy_slots:
            # Check if gap between current_time and next busy slot is big enough
            if current_time + appointment_duration <= slot_start:
                # Is this gap during working hours?
                if is_within_working_hours(
                    current_time, current_time + appointment_duration
                ):
                    # found available slot
                    return current_time
            # Move current_time forward if this busy slot ends after it
            if slot_end > current_time:
                current_time = slot_end

        # After checking all busy slots, check remaining time window (till 7 days ahead)
        search_window_end = requested_time + 7 * 24 * 60
        while current_time + appointment_duration <= search_window_end:
            if is_within_working_hours(
                current_time, current_time + appointment_duration
            ):
                return current_time
            # Move to next minute (could be optimized to jump by working hours)
            current_time += 1

        raise Exception("No available slot found in the next 7 days.")


def is_time_available(
    engine,
    environment,
    practitioner_object: models.Practitioner,
    start_time: int,
    duration: int,
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


# TODO: Make sure that appointments start at somewhat regular points in time!
def appointment(
    engine,
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
):
    appointment_duration = APPOINTMENT_VISIT_DURATION()
    key = (patient_object.id, practitioner_object.id)

    requested_time = environment.now
    # Step 1: Search for a future time slot
    scheduled_start_time = find_next_available_time(
        engine, requested_time, practitioner_object, appointment_duration
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
        if random.random() < APPOINTMENT_CANCEL_PROBABILITY:
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
    if random.random() < APPOINTMENT_NOSHOW_PROBABILITY:
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
        if random.random() < BTG_ACCESS_PROBABILITY:
            btg_proc = environment.process(
                resource_access_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    event_type=models.AccessEventType.EMERGENCY,
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
    appointment_id: str | None,
    appointment_start: int,
    appointment_duration: int,
):
    """Simulates an encounter inside the timeframe of the appointment."""
    print(
        f"[{environment.now:>4}] {practitioner_object.id} begins ENCOUNTER with {patient_object.id}"
    )

    # Calculate encounter duration
    encounter_duration = max(
        min(APPOINTMENT_VISIT_DURATIONS),
        random.randint(appointment_duration // 2, appointment_duration),
    )

    # Calculate maximum possible start delay
    max_delay = appointment_duration - encounter_duration
    start_delay = random.randint(0, max_delay)

    # Calculate actual start and end times
    encounter_start = appointment_start + start_delay
    encounter_end = encounter_start + encounter_duration
    remaining_appointment_duration = appointment_duration - start_delay

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
    if random.random() < BTG_ACCESS_PROBABILITY:
        btg_proc = environment.process(
            resource_access_process(
                environment=environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
                event_type=models.AccessEventType.EMERGENCY,
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
                remaining_appointment_duration=remaining_appointment_duration,
                encounter_id=encounter_id,
            )
        )


def biased_times(start_time, end_time, count: int, bias_strength: float = 2.0):
    # Total minutes in the interval
    total_minutes = end_time - start_time
    if total_minutes == 0:
        raise ValueError("total_minutes = 0, so no biased times can be generated!")

    points: set[int] = set()
    while len(points) < count:
        # Generate biased random number between 0 and 1
        r = random.random() ** bias_strength
        minute_offset = int(r * total_minutes)
        points.add(minute_offset)

    # Convert offsets back to datetime objects
    return [start_time + offset for offset in sorted(points)]


def observations(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
    encounter_start: int,
    remaining_appointment_duration: int,
    encounter_id: str | None,
):
    """
    Simulates observations (possibly recorded
    inside the timeframe of an encounter).
    """
    # In case remaining_appointment_duration is zero, then we should generate
    # one or more observations not tied to an encounter or appointment
    if remaining_appointment_duration == 0:
        # For generation purposes, assume that the observations take place within
        # a timeframe equal to the minimum duration of an appointment
        appointment_duration = min(APPOINTMENT_VISIT_DURATIONS)
        # Calculate encounter duration
        encounter_duration = random.randint(
            appointment_duration // 2, appointment_duration
        )
        # Calculate maximum possible start delay
        max_delay = appointment_duration - encounter_duration
        start_delay = random.randint(0, max_delay)

        # Calculate actual start and end times
        # encounter_start = appointment_start + start_delay
        # encounter_end = encounter_start + encounter_duration
        remaining_appointment_duration = appointment_duration - start_delay
        # # Singleton Observation event
        # count = 1
        # obs_times = [encounter_start]
    # else:
    count = random.randint(1, OBSERVATIONS_MAX)
    obs_times = biased_times(
        encounter_start,
        encounter_start + remaining_appointment_duration,
        count=count,
        bias_strength=1.75,
    )

    for i in range(count):
        code, display = OBSERVATION_CODES[i % OBSERVATIONS_MAX]
        value = (
            f"{random.uniform(96, 99):.1f} °F"
            if i == 0
            else str(random.randint(60, 100))
        )
        print(f"[{obs_times[i]:>4}] Observation {i+1} for patient {patient_object.id}")

        obs_id = fhir_logger.log_observation(
            patient_id=patient_object.id,
            practitioner_id=practitioner_object.id,
            timestamp=obs_times[i],
            code=code,
            value=value,
            encounter_id=encounter_id,
        )

        # Add potential BTG event during observation
        if random.random() < BTG_ACCESS_PROBABILITY:
            yield environment.process(
                resource_access_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    event_type=models.AccessEventType.EMERGENCY,
                    context_resource_type="Observation",
                    context_resource_id=obs_id,
                )
            )

        yield environment.timeout(0)


def resource_access_process(
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
    event_type: models.AccessEventType,
    context_resource_type: Union[str, None] = None,
    context_resource_id: Union[str, None] = None,
):
    """Simulates a logged access event"""
    # No delay before access event occurs
    yield environment.timeout(0)

    if event_type == models.AccessEventType.EMERGENCY:
        purpose = models.AccessEventPurpose.EMERGENCY

        # Determine purpose of emergency access event based on context
        if context_resource_type:
            purpose_of_event = f"Emergency access during {context_resource_type}"
        else:
            purpose_of_event = "Emergency access - standalone event"

    elif event_type == models.AccessEventType.CARE:
        purpose = models.AccessEventPurpose.CARE
        # Determine purpose of normal access event based on context
        if context_resource_type:
            purpose_of_event = f"Normal access during {context_resource_type}"
        else:
            purpose_of_event = "Normal access - standalone event"
    else:
        raise ValueError(
            f"The handling of {event_type} events has not yet been implemented!"
        )

    # Log the access event
    fhir_logger.log_access_event(
        patient_id=patient_object.id,
        recorded=environment.now,
        practitioner_id=practitioner_object.id,
        action="R",  # R=Read
        event_type=event_type,
        purpose=purpose,
        purpose_of_event=purpose_of_event,
        target_resource_type=context_resource_type,
        target_resource_id=context_resource_id,
        outcome="success",
    )

    print(
        f"[{environment.now:>4}] AUDIT EVENT {event_type}"
        f" by {practitioner_object.id} for {patient_object.id}"
        f"{f' during {context_resource_type}' if context_resource_type else ''}"
    )


def standalone_access_event_generator(
    environment, fhir_logger, practitioner_objects, patient_objects
):
    """
    Independent process that generates standalone access events
    (either ordinary or break-the-class emergency events)
    """
    while True:
        # Wait random interval (1-24 hours in simulation minutes)
        # before deciding of a random access event should be triggered
        yield environment.timeout(random.randint(60, 60 * 24))

        if random.random() < STANDALONE_BTG_ACCESS_PROBABILITY:
            # Randomly select practitioner and patient
            practitioner_id = random.choice(list(practitioner_objects.keys()))
            patient_id = random.choice(list(patient_objects.keys()))
            practitioner = practitioner_objects[practitioner_id]
            patient = patient_objects[patient_id]

            # Trigger BTG access event
            environment.process(
                resource_access_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner,
                    patient_object=patient,
                    event_type=models.AccessEventType.EMERGENCY,
                )
            )
        elif random.random() < STANDALONE_NORMAL_ACCESS_PROBABILITY:
            # Randomly select practitioner and patient
            practitioner_id = random.choice(list(practitioner_objects.keys()))
            patient_id = random.choice(list(patient_objects.keys()))
            practitioner = practitioner_objects[practitioner_id]
            patient = patient_objects[patient_id]

            # Trigger a normal access event
            environment.process(
                resource_access_process(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner,
                    patient_object=patient,
                    event_type=models.AccessEventType.CARE,
                )
            )


def choose_event_type() -> str:
    return random.choices(
        population=list(EVENT_TYPE_WEIGHTS.keys()),
        weights=list(EVENT_TYPE_WEIGHTS.values()),
        k=1,
    )[0]


# === Patient Process ===
def patient_process(
    engine,
    environment,
    fhir_logger: models.FHIRLogger,
    practitioner_object: models.Practitioner,
    patient_object: models.Patient,
):
    """Simulates a patient triggering events according to probability rules."""
    # An event sequence can start with one of the following events:
    # - Appointment
    # - Encounter
    # - Observation
    event_type = choose_event_type()

    if event_type == "Appointment":
        yield environment.process(
            appointment(
                engine,
                environment=environment,
                fhir_logger=fhir_logger,
                practitioner_object=practitioner_object,
                patient_object=patient_object,
            )
        )
    elif event_type == "Encounter":
        encounter_duration = APPOINTMENT_VISIT_DURATION()
        current_time = environment.now

        # Check if time is available right now
        if is_time_available(
            engine,
            environment,
            practitioner_object,
            current_time,
            duration=encounter_duration,
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
        if is_time_available(
            engine, environment, practitioner_object, current_time, duration=1
        ):
            yield environment.process(
                observations(
                    environment=environment,
                    fhir_logger=fhir_logger,
                    practitioner_object=practitioner_object,
                    patient_object=patient_object,
                    encounter_start=current_time,
                    remaining_appointment_duration=0,
                    encounter_id=None,
                )
            )
        else:
            print(
                f"[{current_time:>4}] Could not record observation - practitioner busy"
            )


def fill_patient_queues(
    environment, patient_queues, patient_objects: list, interval=24 * 60
):
    number_of_practitioners = len(patient_queues)
    count = 0
    # Stop after all patients have been assigned
    while count < len(patient_objects):
        patient_object = patient_objects[count]
        # Round-robin index
        index = count % number_of_practitioners
        key = list(patient_queues.keys())[index]
        # Spread out the patient arrivals over time
        # arrival_time = int(random.expovariate(1.0 / interval))
        # arrival_time = random.randint(lambda_2, lambda_1)
        # arrival_time = sample_cooldown_time()
        arrival_time = random.randint(lambda_1, lambda_4)
        yield environment.timeout(arrival_time)
        queue = patient_queues[key]
        yield queue.put(patient_object)
        print(
            f"[{environment.now}] Patient {patient_object.id} assigned to queue {key}"
        )
        count += 1


# === Practitioner process ===
def practitioner_process(
    environment,
    fhir_logger,
    practitioner_id,
    practitioner_object,
    patient_queue,
    active_patient_count,
    last_patient_activity,
    patient_objects,
    engine,
):
    while True:
        # Population maintenance
        if active_patient_count.level < PATIENT_MIN_POPULATION or (
            random.random() < PATIENT_ADMITTANCE_PROBABILITY
            and active_patient_count.level < PATIENT_TARGET_POPULATION
        ):
            new_patients_needed = PATIENT_TARGET_POPULATION - active_patient_count.level
            _new_patients = [create_patient(engine) for _ in range(new_patients_needed)]
            new_patients = {patient.id: patient for patient in _new_patients}

            environment.process(
                fill_patient_queues(
                    environment,
                    {practitioner_id: patient_queue},
                    list(new_patients.values()),
                )
            )
            yield active_patient_count.put(new_patients_needed)
            print(
                f"[{environment.now:>4}] Added {new_patients_needed} new patients (Total: {active_patient_count.level})"
            )

        patient_object = yield patient_queue.get()

        current_time = environment.now

        # Cooldown check
        if patient_object.id in last_patient_activity:
            (recorded_time, cooldown) = last_patient_activity[patient_object.id]
            time_since_last = current_time - recorded_time

            if time_since_last < cooldown:
                remaining_cooldown = cooldown - time_since_last
                yield environment.timeout(remaining_cooldown)
                # Put back in correct queue
                yield patient_queue.put(patient_object)
                continue

        # Process patient
        main_process = environment.process(
            patient_process(
                engine, environment, fhir_logger, practitioner_object, patient_object
            )
        )
        yield main_process

        # Update activity
        last_patient_activity[patient_object.id] = (
            environment.now,
            PATIENT_SCHEDULING_COOLDOWN_IN_MINUTES(),
        )

        # Discharge logic
        if random.random() < PATIENT_DISCHARGE_PROBABILITY:
            yield active_patient_count.get(1)
            # Patient discharged - remove from tracking
            if patient_object.id in last_patient_activity:
                del last_patient_activity[patient_object.id]
            print(
                f"[{environment.now:>4}] Patient {patient_object.id} discharged (Remaining: {active_patient_count.level - 1})"
            )
        else:
            # Patient continues - requeue immediately (cooldown enforced on next pull)
            patient_queue.put(patient_object)
            print(
                f"[{environment.now:>4}] Patient {patient_object.id} re-queued (eligible after cooldown)"
            )


# === Scheduler ===
def scheduler(
    engine,
    environment,
    fhir_logger,
    patient_queues,
    practitioner_objects,
    patient_objects,
):
    active_patient_count = simpy.Container(
        environment, init=len(patient_objects), capacity=PATIENT_TARGET_POPULATION
    )
    last_patient_activity = {}

    print(f"[{environment.now:>4}] Starting with {active_patient_count.level} patients")

    # Initial queue filling
    environment.process(
        fill_patient_queues(environment, patient_queues, list(patient_objects.values()))
    )

    # Create a process for each practitioner
    practitioner_processes = [
        environment.process(
            practitioner_process(
                environment,
                fhir_logger,
                practitioner_id,
                practitioner_object,
                patient_queues[practitioner_id],
                active_patient_count,
                last_patient_activity,
                patient_objects,
                engine,
            )
        )
        for practitioner_id, practitioner_object in practitioner_objects.items()
    ]

    # Run all practitioner processes concurrently
    yield simpy.events.AllOf(environment, practitioner_processes)


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
        raise ValueError("Other roles than 'doctor' is currently not supported.")


# === Main ===
def run_simulation(engine, pracitioners: int, patients: int):

    # === Simulation Setup ===
    environment = simpy.Environment()

    # Create patients
    _patient_objects = [create_patient(engine) for _ in range(patients)]
    patient_objects = {patient.id: patient for patient in _patient_objects}

    _practitioner_objects = [
        create_practitioner(engine, environment) for _ in range(pracitioners)
    ]
    practitioner_objects = {
        practitioner.id: practitioner for practitioner in _practitioner_objects
    }
    patient_queues = {
        practitioner_object.id: simpy.Store(environment)
        for practitioner_object in _practitioner_objects
    }

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
            patient_queues=patient_queues,
            practitioner_objects=practitioner_objects,
            patient_objects=patient_objects,
        )
    )

    environment.process(
        standalone_access_event_generator(
            environment, fhir_logger, practitioner_objects, patient_objects
        )
    )

    # Run simulation
    environment.run(until=SIMULATION_DURATION_IN_MINUTES)


def main():
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
        patients=NUMBER_OF_PATIENTS,
    )
    print(f"[{SIMULATION_DURATION_IN_MINUTES:>4}] REACHED END OF SIMULATION.")


# Run it
if __name__ == "__main__":
    main()
