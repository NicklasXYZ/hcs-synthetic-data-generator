# # # export_data.py
# # import json
# # from sqlmodel import Session, select, create_engine
# # from datetime import datetime
# # import models


# # def json_serial(obj):
# #     """JSON serializer for objects not serializable by default"""
# #     if isinstance(obj, datetime):
# #         return obj.isoformat()
# #     raise TypeError(f"Type {type(obj)} not serializable")


# # def export_to_json(engine):
# #     with Session(engine) as session:
# #         # Export Patients
# #         patients = session.exec(select(models.Patient)).all()
# #         with open("./ids-data/docs/data/patients.json", "w") as f:
# #             json.dump(
# #                 [p.model_dump() for p in patients],
# #                 f,
# #                 indent=4,
# #                 sort_keys=True,
# #                 default=str,
# #             )

# #         # Export Practitioners
# #         practitioners = session.exec(select(models.Practitioner)).all()
# #         with open("./ids-data/docs/data/practitioners.json", "w") as f:
# #             json.dump(
# #                 [p.model_dump() for p in practitioners],
# #                 f,
# #                 indent=4,
# #                 sort_keys=True,
# #                 default=str,
# #             )

# #         # Export Events (combine multiple tables)
# #         events = []

# #         # Add appointments
# #         appointments = session.exec(select(models.Appointment)).all()
# #         for a in appointments:
# #             events.append(
# #                 {
# #                     "type": "appointment",
# #                     "id": a.id,
# #                     "patient_id": a.patient_id,
# #                     "practitioner_id": a.practitioner_id,
# #                     "start": a.scheduled_start_time,
# #                     "end": a.scheduled_start_time + a.duration,
# #                     "status": a.status,
# #                     "data": a.model_dump(),
# #                 }
# #             )

# #         # Add encounters
# #         encounters = session.exec(select(models.Encounter)).all()
# #         for e in encounters:
# #             events.append(
# #                 {
# #                     "type": "encounter",
# #                     "id": e.id,
# #                     "patient_id": e.patient_id,
# #                     "practitioner_id": e.practitioner_id,
# #                     "start": e.actual_start_time,
# #                     "end": e.actual_start_time + e.duration,
# #                     "data": e.model_dump(),
# #                 }
# #             )

# #         # Add BTG events
# #         btg_events = session.exec(select(models.BTGEvent)).all()
# #         for b in btg_events:
# #             events.append(
# #                 {
# #                     "type": "btg",
# #                     "id": b.id,
# #                     "patient_id": b.patient_id,
# #                     "practitioner_id": b.practitioner_id,
# #                     "timestamp": b.recorded,
# #                     "data": b.model_dump(),
# #                 }
# #             )

# #         with open("./ids-data/docs/data/events.json", "w") as f:
# #             json.dump(
# #                 events, f, indent=4, sort_keys=True, default=str
# #             )  # , default=json_serial)


# # if __name__ == "__main__":
# #     engine = create_engine("sqlite:///hospital_simulation.db")
# #     export_to_json(engine)

# # export_data.py
# import json
# from sqlmodel import Session, select, create_engine
# from datetime import datetime, timedelta
# import models


# def convert_minutes_to_monday(minutes):
#     """
#     Convert minutes to a datetime starting from Monday 00:00 of the current week.
#     If minutes exceed one week, it will roll over to the following weeks.
#     """
#     # Get the most recent Monday at 00:00
#     # today = datetime.now()
#     today = datetime(2023, 11, 6)  # November 6, 2023 (a Monday)
#     monday = today - timedelta(days=today.weekday())
#     monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

#     # Add the minutes to Monday 00:00
#     return monday + timedelta(minutes=minutes)


# def export_to_json(engine):
#     with Session(engine) as session:
#         # [Previous code for patients and practitioners remains the same...]

#         # Export Events (combine multiple tables)
#         events = []

#         # Add appointments
#         appointments = session.exec(select(models.Appointment)).all()
#         for a in appointments:
#             events.append(
#                 {
#                     "type": "appointment",
#                     "id": a.id,
#                     "patient_id": a.patient_id,
#                     "practitioner_id": a.practitioner_id,
#                     "start": convert_minutes_to_monday(
#                         a.scheduled_start_time
#                     ).isoformat(),
#                     "end": convert_minutes_to_monday(
#                         a.scheduled_start_time + a.duration
#                     ).isoformat(),
#                     "status": a.status,
#                     "data": a.model_dump(),
#                 }
#             )

#         # Add encounters
#         encounters = session.exec(select(models.Encounter)).all()
#         for e in encounters:
#             events.append(
#                 {
#                     "type": "encounter",
#                     "id": e.id,
#                     "patient_id": e.patient_id,
#                     "practitioner_id": e.practitioner_id,
#                     "start": convert_minutes_to_monday(e.actual_start_time).isoformat(),
#                     "end": convert_minutes_to_monday(
#                         e.actual_start_time + e.duration
#                     ).isoformat(),
#                     "data": e.model_dump(),
#                 }
#             )

#         # Add BTG events
#         btg_events = session.exec(select(models.BTGEvent)).all()
#         for b in btg_events:
#             events.append(
#                 {
#                     "type": "btg",
#                     "id": b.id,
#                     "patient_id": b.patient_id,
#                     "practitioner_id": b.practitioner_id,
#                     "timestamp": convert_minutes_to_monday(b.recorded).isoformat(),
#                     "data": b.model_dump(),
#                 }
#             )

#         with open("./ids-data/docs/data/events.json", "w") as f:
#             json.dump(events, f, indent=4, sort_keys=True, default=str)


# if __name__ == "__main__":
#     engine = create_engine("sqlite:///hospital_simulation.db")
#     export_to_json(engine)


# export_data.py
import json
from sqlmodel import Session, select, create_engine
from datetime import datetime, timedelta
import models


def convert_minutes_to_monday(minutes):
    """
    Convert minutes to a datetime starting from Monday 00:00 of the current week.
    If minutes exceed one week, it will roll over to the following weeks.
    """
    # Get the most recent Monday at 00:00
    # today = datetime.now()
    today = datetime(2023, 11, 6)  # November 6, 2023 (a Monday)
    monday = today - timedelta(days=today.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    # Add the minutes to Monday 00:00
    return monday + timedelta(minutes=minutes)


def export_to_json(engine):
    with Session(engine) as session:
        # Export Patients
        patients = session.exec(select(models.Patient)).all()
        with open("./ids-data/docs/data/patients.json", "w") as f:
            json.dump(
                [p.model_dump() for p in patients],
                f,
                indent=4,
                sort_keys=True,
                default=str,
            )

        # Export Practitioners
        practitioners = session.exec(select(models.Practitioner)).all()
        with open("./ids-data/docs/data/practitioners.json", "w") as f:
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
                    "type": "appointment",
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
                    "type": "encounter",
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
                    "type": "observation",
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

        # Add BTG events
        btg_events = session.exec(select(models.BTGEvent)).all()
        for b in btg_events:
            events.append(
                {
                    "type": "btg",
                    "id": b.id,
                    "patient_id": b.patient_id,
                    "practitioner_id": b.practitioner_id,
                    "timestamp": convert_minutes_to_monday(b.recorded).isoformat(),
                    "data": b.model_dump(),
                }
            )

        with open("./ids-data/docs/data/events.json", "w") as f:
            json.dump(events, f, indent=4, sort_keys=True, default=str)


if __name__ == "__main__":
    engine = create_engine("sqlite:///hospital_simulation.db")
    export_to_json(engine)