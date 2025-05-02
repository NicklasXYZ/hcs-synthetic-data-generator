import json
from sqlmodel import Session, select, create_engine
from datetime import datetime, timedelta
import models
import random

MAX_PRACTITIONERS = 10
MAX_PATIENTS = 25

random.seed(123)

def convert_minutes_to_monday(minutes):
    """
    Convert minutes to a datetime starting from Monday 00:00 of the current week.
    If minutes exceed one week, it will roll over to the following weeks.
    """
    # Get a Monday at 00:00 (November 6, 2023)
    today = datetime(2023, 11, 6)
    monday = today - timedelta(days=today.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    # Add the minutes to Monday 00:00
    return monday + timedelta(minutes=minutes)


def export_to_json(engine):
    with Session(engine) as session:
        # Export Patients
        patients = session.exec(select(models.Patient)).all()
        with open("./docs/data/patients.json", "w") as f:
            json.dump(
                [p.model_dump() for p in patients],
                f,
                indent=4,
                sort_keys=True,
                default=str,
            )

        # Export Practitioners
        practitioners = session.exec(select(models.Practitioner)).all()
        with open("./docs/data/practitioners.json", "w") as f:
            json.dump(
                [p.model_dump() for p in practitioners],
                f,
                indent=4,
                sort_keys=True,
                default=str,
            )

        # Export Events (combine multiple tables)
        events = []

        # Add appointments
        appointments = session.exec(select(models.Appointment)).all()
        for a in appointments:
            events.append(
                {
                    "type": "Appointment",
                    "id": a.id,
                    "patient_id": a.patient_id,
                    "practitioner_id": a.practitioner_id,
                    "start": convert_minutes_to_monday(
                        a.scheduled_start_time
                    ).isoformat(),
                    "end": convert_minutes_to_monday(
                        a.scheduled_start_time + a.duration
                    ).isoformat(),
                    "status": a.status,
                    "data": a.model_dump(),
                }
            )

        # Add encounters
        encounters = session.exec(select(models.Encounter)).all()
        for e in encounters:
            events.append(
                {
                    "type": "Encounter",
                    "id": e.id,
                    "patient_id": e.patient_id,
                    "practitioner_id": e.practitioner_id,
                    "start": convert_minutes_to_monday(e.actual_start_time).isoformat(),
                    "end": convert_minutes_to_monday(
                        e.actual_start_time + e.duration
                    ).isoformat(),
                    "data": e.model_dump(),
                }
            )

        # Add observations
        observations = session.exec(select(models.Observation)).all()
        for o in observations:
            events.append(
                {
                    "type": "Observation",
                    "id": o.id,
                    "patient_id": o.patient_id,
                    "practitioner_id": o.practitioner_id,
                    "timestamp": convert_minutes_to_monday(o.timestamp).isoformat(),
                    "code": o.code,
                    "value": o.value,
                    "encounter_id": o.encounter_id,
                    "data": o.model_dump(),
                }
            )

        # Add audit events
        audit_events = session.exec(select(models.AuditEvent)).all()
        for b in audit_events:
            events.append(
                {
                    "type": "AuditEvent",
                    "id": b.id,
                    "patient_id": b.patient_id,
                    "practitioner_id": b.practitioner_id,
                    "timestamp": convert_minutes_to_monday(b.recorded).isoformat(),
                    "data": b.model_dump(),
                }
            )

        with open("./docs/data/events.json", "w") as f:
            json.dump(events, f, indent=4, sort_keys=True, default=str)

        # Create sample datasets
        create_sample_datasets(session, patients, practitioners)


def create_sample_datasets(session, patients, practitioners):
    # Sample 5 practitioners
    sampled_practitioners = random.sample(practitioners, MAX_PRACTITIONERS)
    sampled_practitioner_ids = {p.id for p in sampled_practitioners}

    # Sample 10 patients per practitioner
    sampled_patients = []
    sampled_patient_ids = set()
    for practitioner in sampled_practitioners:
        practitioner_patients = session.exec(
            select(models.Patient).where(
                models.Patient.id.in_(
                    select(models.Appointment.patient_id).where(
                        models.Appointment.practitioner_id == practitioner.id
                    )
                )
            )
        ).all()
        sampled_patients.extend(
            random.sample(
                practitioner_patients, min(MAX_PATIENTS, len(practitioner_patients))
            )
        )
        sampled_patient_ids.update(p.id for p in sampled_patients)

    # Query events related to sampled patients and practitioners
    sampled_events = (
        session.exec(
            select(models.Appointment).where(
                (models.Appointment.patient_id.in_(sampled_patient_ids))
                & (models.Appointment.practitioner_id.in_(sampled_practitioner_ids))
            )
        ).all()
        + session.exec(
            select(models.Encounter).where(
                (models.Encounter.patient_id.in_(sampled_patient_ids))
                & (models.Encounter.practitioner_id.in_(sampled_practitioner_ids))
            )
        ).all()
        + session.exec(
            select(models.Observation).where(
                (models.Observation.patient_id.in_(sampled_patient_ids))
                & (models.Observation.practitioner_id.in_(sampled_practitioner_ids))
            )
        ).all()
        + session.exec(
            select(models.AuditEvent).where(
                (models.AuditEvent.patient_id.in_(sampled_patient_ids))
                & (models.AuditEvent.practitioner_id.in_(sampled_practitioner_ids))
            )
        ).all()
    )

    # Convert sampled events to the required format
    sampled_events_data = []
    for event in sampled_events:
        if isinstance(event, models.Appointment):
            sampled_events_data.append(
                {
                    "type": "Appointment",
                    "id": event.id,
                    "patient_id": event.patient_id,
                    "practitioner_id": event.practitioner_id,
                    "start": convert_minutes_to_monday(
                        event.scheduled_start_time
                    ).isoformat(),
                    "end": convert_minutes_to_monday(
                        event.scheduled_start_time + event.duration
                    ).isoformat(),
                    "status": event.status,
                    "data": event.model_dump(),
                }
            )
        elif isinstance(event, models.Encounter):
            sampled_events_data.append(
                {
                    "type": "Encounter",
                    "id": event.id,
                    "patient_id": event.patient_id,
                    "practitioner_id": event.practitioner_id,
                    "start": convert_minutes_to_monday(
                        event.actual_start_time
                    ).isoformat(),
                    "end": convert_minutes_to_monday(
                        event.actual_start_time + event.duration
                    ).isoformat(),
                    "data": event.model_dump(),
                }
            )
        elif isinstance(event, models.Observation):
            sampled_events_data.append(
                {
                    "type": "Observation",
                    "id": event.id,
                    "patient_id": event.patient_id,
                    "practitioner_id": event.practitioner_id,
                    "timestamp": convert_minutes_to_monday(event.timestamp).isoformat(),
                    "code": event.code,
                    "value": event.value,
                    "encounter_id": event.encounter_id,
                    "data": event.model_dump(),
                }
            )
        elif isinstance(event, models.AuditEvent):
            sampled_events_data.append(
                {
                    "type": "AuditEvent",
                    "id": event.id,
                    "patient_id": event.patient_id,
                    "practitioner_id": event.practitioner_id,
                    "timestamp": convert_minutes_to_monday(event.recorded).isoformat(),
                    "data": event.model_dump(),
                }
            )

    # Export sampled patients
    with open("./docs/data/patients_sample.json", "w") as f:
        json.dump(
            [p.model_dump() for p in sampled_patients],
            f,
            indent=4,
            sort_keys=True,
            default=str,
        )

    # Export sampled practitioners
    with open("./docs/data/practitioners_sample.json", "w") as f:
        json.dump(
            [p.model_dump() for p in sampled_practitioners],
            f,
            indent=4,
            sort_keys=True,
            default=str,
        )

    # Export sampled events
    with open("./docs/data/events_sample.json", "w") as f:
        json.dump(sampled_events_data, f, indent=4, sort_keys=True, default=str)


if __name__ == "__main__":
    engine = create_engine("sqlite:///hospital_simulation.db")
    export_to_json(engine)
