from athena.schemas.grading_criterion import GradingCriterion, StructuredGradingInstruction

# Grading criteria for hospital management system
HOSPITAL_GRADING_CRITERIA = [
    GradingCriterion(
        id=1,
        title="Appointment Class Structure",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=1, credits=2.0, grading_scale="Good",
                instruction_description="Appointment class must have date and status attributes.",
                feedback="Appointment class has the required date and status attributes.", usage_count=0
            )
        ]
    ),
    GradingCriterion(
        id=2,
        title="Doctor Inheritance and Attributes",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=2, credits=2.0, grading_scale="Good",
                instruction_description="Doctor must inherit from Person AND have both specialization and licenseNumber attributes. No partial credit.",
                feedback="Doctor correctly inherits from Person and has both required attributes.", usage_count=0
            )
        ]
    ),
    GradingCriterion(
        id=3,
        title="Nurse Inheritance and Attributes",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=3, credits=2.0, grading_scale="Good",
                instruction_description="Nurse must inherit from Person and have department and shift attributes.",
                feedback="Nurse correctly inherits from Person and has the required attributes.", usage_count=0
            )
        ]
    ),
    GradingCriterion(
        id=4,
        title="Patient Attributes",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=4, credits=2.0, grading_scale="Good",
                instruction_description="Patient class must have the attributes patientId and medicalHistory.",
                feedback="Patient class has the required patientId and medicalHistory attributes.", usage_count=0
            )
        ]
    ),
    GradingCriterion(
        id=5,
        title="Department-Staff Composition",
        structured_grading_instructions=[
            StructuredGradingInstruction(
                id=5, credits=2.0, grading_scale="Good",
                instruction_description="Department must have a composition relationship with Staff.",
                feedback="Department and Staff are correctly in a composition relationship.", usage_count=0
            )
        ]
    )
]

# Problem statement and grading instructions
HOSPITAL_PROBLEM_STATEMENT = (
    "Design a UML class diagram for a hospital management system that handles patient care, staff management, and medical treatments. "
    "The system needs to manage different types of medical staff (doctors and nurses) who have common personal information like name and id but different professional qualifications. "
    "Doctors need to be tracked with their medical specialization and license information, while nurses need to be assigned to specific departments and work shifts. "
    "Patients need to be uniquely identified and their medical history needs to be maintained. "
    "The system must track appointments between patients and medical staff, including their status and date. "
    "The hospital is organized into departments, each with its own staff members. "
    "Medical treatments need to be recorded, including which doctor provided the treatment and which patient received it. "
    "Some medical staff members need to perform specific medical procedures that require special certification."
)

HOSPITAL_GRADING_INSTRUCTIONS = (
    "1. Appointment class must have date and status attributes.\n"
    "2. Doctor must inherit from Person and have specialization and licenseNumber attributes.\n"
    "3. Nurse must inherit from Person and have department and shift attributes.\n"
    "4. Patient class must have a name attribute for identification.\n"
    "5. Department must have a composition relationship with Staff.\n"
)

# Example solution and submission JSON
HOSPITAL_EXAMPLE_SOLUTION = '''
{
    "type": "ClassDiagram",
    "elements": {
        "1": {"id": "1", "type": "Class", "name": "Person", "attributes": ["name: String", "id: String"], "methods": [], "isAbstract": true},
        "2": {"id": "2", "type": "Class", "name": "Doctor", "attributes": ["specialization: String", "licenseNumber: String"], "methods": []},
        "3": {"id": "3", "type": "Class", "name": "Nurse", "attributes": ["department: String", "shift: String"], "methods": []},
        "4": {"id": "4", "type": "Class", "name": "Patient", "attributes": ["patientId: String", "medicalHistory: String"], "methods": []},
        "5": {"id": "5", "type": "Class", "name": "Appointment", "attributes": ["date: DateTime", "status: String"], "methods": []},
        "6": {"id": "6", "type": "Class", "name": "Department", "attributes": ["name: String"], "methods": []},
        "7": {"id": "7", "type": "Class", "name": "Staff", "attributes": [], "methods": []},
        "8": {"id": "8", "type": "Class", "name": "Treatment", "attributes": ["date: DateTime", "description: String"], "methods": []},
        "9": {"id": "9", "type": "Interface", "name": "IMedicalStaff", "attributes": [], "methods": ["performProcedure()"]}
    },
    "relationships": {
        "r1": {"id": "r1", "type": "Inheritance", "source": {"element": "2"}, "target": {"element": "1"}},
        "r2": {"id": "r2", "type": "Inheritance", "source": {"element": "3"}, "target": {"element": "1"}},
        "r3": {"id": "r3", "type": "Aggregation", "source": {"element": "4"}, "target": {"element": "5"}},
        "r4": {"id": "r4", "type": "Composition", "source": {"element": "6"}, "target": {"element": "7"}},
        "r5": {"id": "r5", "type": "Implementation", "source": {"element": "2"}, "target": {"element": "9"}},
        "r6": {"id": "r6", "type": "Association", "source": {"element": "8"}, "target": {"element": "2"}},
        "r7": {"id": "r7", "type": "Association", "source": {"element": "8"}, "target": {"element": "4"}}
    }
}
'''

HOSPITAL_SUBMISSION = '''
{
    "type": "ClassDiagram",
    "elements": {
        "1": {"id": "1", "type": "Class", "name": "Person", "attributes": ["name: String"], "methods": []},
        "2": {"id": "2", "type": "Class", "name": "Doctor", "attributes": ["specialization: String"], "methods": []},
        "3": {"id": "3", "type": "Class", "name": "Nurse", "attributes": ["shift: String"], "methods": []},
        "4": {"id": "4", "type": "Class", "name": "Patient", "attributes": [], "methods": []},
        "5": {"id": "5", "type": "Class", "name": "Appointment", "attributes": [], "methods": []},
        "6": {"id": "6", "type": "Class", "name": "Department", "attributes": [], "methods": []},
        "7": {"id": "7", "type": "Class", "name": "Staff", "attributes": [], "methods": []},
        "8": {"id": "8", "type": "Class", "name": "Treatment", "attributes": [], "methods": []},
        "9": {"id": "9", "type": "Interface", "name": "IMedicalStaff", "attributes": [], "methods": []}
    },
    "relationships": {
        "r1": {"id": "r1", "type": "Inheritance", "source": {"element": "2"}, "target": {"element": "1"}},
        "r2": {"id": "r2", "type": "Inheritance", "source": {"element": "3"}, "target": {"element": "1"}},
        "r3": {"id": "r3", "type": "Association", "source": {"element": "4"}, "target": {"element": "5"}},
        "r4": {"id": "r4", "type": "Association", "source": {"element": "6"}, "target": {"element": "7"}},
        "r5": {"id": "r5", "type": "Implementation", "source": {"element": "2"}, "target": {"element": "9"}},
        "r6": {"id": "r6", "type": "Association", "source": {"element": "8"}, "target": {"element": "2"}},
        "r7": {"id": "r7", "type": "Association", "source": {"element": "8"}, "target": {"element": "4"}}
    }
}
''' 