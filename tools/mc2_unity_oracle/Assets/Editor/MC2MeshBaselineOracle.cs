using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text;
using MagicaCloth2;
using Unity.Burst;
using Unity.Collections;
using Unity.Collections.LowLevel.Unsafe;
using Unity.Mathematics;
using UnityEditor;
using UnityEngine;

namespace HoTools.MC2Oracle.Editor
{
    public static class MC2MeshBaselineOracle
    {
        private const string MC2Version = "2.18.1";
        private const string MC2Commit = "418f89ff31a45bb4b2336641ad5907a1110eabea";

        private sealed class OracleCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int2[] Edges;
            public int3[] Triangles;
            public int[][] Adjacency;
            public bool CompareToHoTools = true;
            public string Note = string.Empty;
        }

        private sealed class OracleDump
        {
            public byte[] FinalAttributes;
            public int[] Parents;
            public int2[] ChildRanges;
            public int[] ChildData;
            public byte[] BaselineFlags;
            public int2[] BaselineRanges;
            public int[] BaselineData;
            public int[] Roots;
            public float[] Depths;
            public float3[] LocalPositions;
            public float4[] LocalRotations;
        }

        private sealed class ProxyCase
        {
            public string Id;
            public float3[] Positions;
            public float3[] Normals;
            public float3[] Tangents;
            public float2[] Uvs;
            public byte[] Attributes;
            public int2[] Lines = Array.Empty<int2>();
            public int3[] Triangles = Array.Empty<int3>();
            public string Note = string.Empty;
        }

        private sealed class ProxyDump
        {
            public byte[] FinalAttributes;
            public int3[] Triangles;
            public int2[] Edges;
            public int2[] VertexToVertexRanges;
            public int[] VertexToVertexData;
            public int2[][] VertexToTriangleRecords;
            public float3[] LocalNormals;
            public float3[] LocalTangents;
            public float3[] VertexBindPosePositions;
            public float4[] VertexBindPoseRotations;
        }

        private sealed class DistanceCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int[] Parents;
            public int2[] Edges;
            public int3[] Triangles;
            public int[][] Adjacency;
            public string Note = string.Empty;
        }

        private sealed class DistanceDump
        {
            public uint[] PackedIndices;
            public int2[] Ranges;
            public int[] Targets;
            public float[] RestSigned;
        }

        private sealed class DistanceRuntimeCase
        {
            public string Id;
            public int[] Targets;
            public float[] RestSigned;
            public string Note = string.Empty;
        }

        private sealed class DistanceRuntimeDump
        {
            public float3[] NextPositions;
            public float3[] VelocityPositions;
        }

        private sealed class BendingCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int2[] Edges;
            public int3[] Triangles;
            public float4x4 InitLocalToWorld = float4x4.identity;
            public string Note = string.Empty;
        }

        private sealed class BendingDump
        {
            public bool CreateReturnedNull;
            public ulong[] RawPackedQuads;
            public int4[] OrderedQuads;
            public float[] RestAngleOrVolume;
            public int[] SignOrVolume;
            public int WriteBufferCount;
            public uint[] RawWriteData;
            public uint[] RawWriteIndices;
            public int2[] WriteRanges;
        }

        private sealed class BendingRuntimeCase
        {
            public string Id;
            public int4[] OrderedQuads;
            public float[] RestAngleOrVolume;
            public sbyte[] SignOrVolume;
            public float3[] NextPositions;
            public byte[] Attributes;
            public float ScaleRatio = 1.0f;
            public float NegativeScaleSign = 1.0f;
            public string Note = string.Empty;
        }

        private sealed class BendingRuntimeDump
        {
            public int[] CountBeforeSum;
            public int[] VectorComponentsBeforeSum;
            public float3[] NextPositionsAfterSum;
            public int[] CountAfterSum;
            public float3[] VectorAfterSum;
        }

        private sealed class ParticleStepDump
        {
            public float3[] BasePositions;
            public float3[] NextPositions;
            public float3[] VelocityPositions;
            public float3[] TempVectorA;
            public float3[] TempVectorB;
            public int[] TempCounts;
            public float[] TempFloats;
        }

        private sealed class ParticleInertiaStepDump
        {
            public float3[] BasePositions;
            public quaternion[] BaseRotations;
            public float3[] StepBasicPositions;
            public quaternion[] StepBasicRotations;
            public float3[] NextPositions;
            public float3[] VelocityPositions;
        }

        private sealed class BaselineStepPoseDump
        {
            public float3[] StepBasicPositions;
            public quaternion[] StepBasicRotations;
        }

        [Serializable]
        private sealed class ParameterRuntimeDump
        {
            public int abi_version = 0;
            public string[] float_fields =
            {
                "gravity",
                "gravity_direction_x", "gravity_direction_y", "gravity_direction_z",
                "gravity_falloff", "stabilization_time_after_reset", "blend_weight",
                "rotational_interpolation", "root_rotation",
                "distance_culling_length", "distance_culling_fade_ratio",
                "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
                "movement_speed_limit", "rotation_speed_limit", "local_inertia",
                "local_movement_speed_limit", "local_rotation_speed_limit", "depth_inertia",
                "centrifugal_acceleration", "particle_speed_limit",
                "teleport_distance", "teleport_rotation",
                "tether_compression_limit", "tether_stretch_limit",
                "distance_velocity_attenuation", "bending_stiffness",
                "angle_restoration_velocity_attenuation", "angle_restoration_gravity_falloff",
                "angle_limit_stiffness", "backstop_radius", "motion_stiffness",
                "collision_dynamic_friction", "collision_static_friction", "cloth_mass",
                "wind_influence", "wind_frequency", "wind_turbulence", "wind_blend",
                "wind_synchronization", "wind_depth_weight", "moving_wind",
                "spring_power", "spring_limit_distance", "spring_normal_limit_ratio", "spring_noise",
            };
            public string[] int_fields =
            {
                "normal_axis", "use_distance_culling", "teleport_mode", "bending_method",
                "use_angle_restoration", "use_angle_limit", "use_max_distance", "use_backstop",
                "collision_mode", "self_collision_mode", "self_collision_sync_mode",
            };
            public string[] curve_fields =
            {
                "damping", "radius", "distance_stiffness", "angle_restoration_stiffness",
                "angle_limit", "max_distance", "backstop_distance", "collision_limit_distance",
                "self_collision_thickness",
            };
            public float[] float_values;
            public int[] int_values;
            public float[] curve_values;
            public int[] curve_shape = { 9, 16 };
        }

        [Serializable]
        private sealed class ParameterOracleOutput
        {
            public string case_id;
            public string oracle_tier = "A";
            public string mc2_version = MC2Version;
            public string mc2_commit = MC2Commit;
            public string source = "Runtime/Cloth/ClothSerializeDataFunction.cs::GetClothParameters";
            public string note;
            public ParameterRuntimeDump expected;
        }

        private sealed class FrameResetDump
        {
            public float3[] WorldPositions;
            public quaternion[] WorldRotations;
            public float3[] NextPositions;
            public float3[] OldPositions;
            public quaternion[] OldRotations;
            public float3[] BasePositions;
            public quaternion[] BaseRotations;
            public float3[] AnimationOldPositions;
            public quaternion[] AnimationOldRotations;
            public float3[] VelocityReferencePositions;
            public float3[] DisplayPositions;
            public float3[] Velocities;
            public float3[] RealVelocities;
            public float[] Friction;
            public float[] StaticFriction;
            public float3[] CollisionNormals;
        }

        private sealed class CenterStaticDump
        {
            public int[] FixedIndices;
            public float3 LocalCenterPosition;
            public float3 InitialLocalGravityDirection;
        }

        private sealed class CenterStepDump
        {
            public float FrameInterpolation;
            public float3 NowWorldPosition;
            public quaternion NowWorldRotation;
            public float3 StepVector;
            public quaternion StepRotation;
            public float StepMoveInertiaRatio;
            public float StepRotationInertiaRatio;
            public float3 InertiaVector;
            public quaternion InertiaRotation;
            public float AngularVelocity;
            public float3 RotationAxis;
            public float ScaleRatio;
            public float GravityDot;
            public float GravityRatio;
            public float VelocityWeight;
            public float BlendWeight;
        }

        private sealed class CenterFrameShiftDump
        {
            public bool KeepTeleport;
            public bool Reset;
            public int UpdateCount;
            public int SkipCount;
            public float Time;
            public float OldTime;
            public float NowUpdateTime;
            public float OldUpdateTime;
            public float FrameUpdateTime;
            public float FrameOldTime;
            public float[] StepFrameInterpolations;
            public float3 FrameComponentShiftVector;
            public quaternion FrameComponentShiftRotation;
            public float3 OldFrameWorldPosition;
            public quaternion OldFrameWorldRotation;
            public float3 NowWorldPosition;
            public quaternion NowWorldRotation;
            public float3 FrameWorldPosition;
            public quaternion FrameWorldRotation;
            public float3 FrameMovingDirection;
            public float FrameMovingSpeed;
            public float3 SmoothingVelocity;
        }

        private sealed class NegativeScaleTeleportDump
        {
            public bool KeepTeleport;
            public bool Reset;
            public bool InertiaShift;
            public bool NegativeScaleTeleport;
            public float NegativeScaleSign;
            public float3 NegativeScaleDirection;
            public float3 NegativeScaleChange;
            public float2 NegativeScaleTriangleSign;
            public float4 NegativeScaleQuaternionValue;
            public float4x4 NegativeScaleMatrix;
            public float3 OldComponentWorldPosition;
            public float3 OldComponentWorldScale;
            public float3 OldAnchorPosition;
            public float3 SmoothingVelocity;
            public float3 OldPosition;
            public quaternion OldRotation;
            public float3 AnimationOldPosition;
            public quaternion AnimationOldRotation;
            public float3 DisplayPosition;
            public float3 Velocity;
            public float3 RealVelocity;
            public float3 FrameComponentShiftVector;
            public quaternion FrameComponentShiftRotation;
            public float3 OldFrameWorldPosition;
            public quaternion OldFrameWorldRotation;
            public float3 NowWorldPosition;
            public quaternion NowWorldRotation;
            public float3 FrameWorldPosition;
            public quaternion FrameWorldRotation;
            public float3 NextPosition;
            public float3 BasePosition;
            public quaternion BaseRotation;
            public float3 VelocityReferencePosition;
            public float Friction;
            public float StaticFriction;
            public float3 CollisionNormal;
        }

        public static void RunBatch()
        {
            string outputDirectory = CommandLineValue("-mc2OracleOutput");
            if (string.IsNullOrWhiteSpace(outputDirectory))
            {
                outputDirectory = Path.Combine(
                    Directory.GetParent(Application.dataPath).FullName,
                    "OracleOutput"
                );
            }
            Directory.CreateDirectory(outputDirectory);

            int written = 0;
            foreach (OracleCase oracleCase in Cases())
            {
                OracleDump dump = RunCase(oracleCase);
                string json = BuildJson(oracleCase, dump);
                string path = Path.Combine(outputDirectory, oracleCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                written++;
            }

            int proxyWritten = 0;
            foreach (ProxyCase proxyCase in ProxyCases())
            {
                ProxyDump dump = RunProxyCase(proxyCase);
                string json = BuildProxyJson(proxyCase, dump);
                string path = Path.Combine(outputDirectory, proxyCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                proxyWritten++;
            }

            int distanceWritten = 0;
            foreach (DistanceCase distanceCase in DistanceCases())
            {
                DistanceDump dump = RunDistanceCase(distanceCase);
                string json = BuildDistanceJson(distanceCase, dump);
                string path = Path.Combine(outputDirectory, distanceCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                distanceWritten++;
            }

            int distanceRuntimeWritten = 0;
            foreach (DistanceRuntimeCase runtimeCase in DistanceRuntimeCases())
            {
                DistanceRuntimeDump dump = RunDistanceRuntimeCase(runtimeCase);
                string json = BuildDistanceRuntimeJson(runtimeCase, dump);
                string path = Path.Combine(outputDirectory, runtimeCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                distanceRuntimeWritten++;
            }

            int bendingWritten = 0;
            foreach (BendingCase bendingCase in BendingCases())
            {
                BendingDump dump = RunBendingCase(bendingCase);
                string json = BuildBendingJson(bendingCase, dump);
                string path = Path.Combine(outputDirectory, bendingCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                bendingWritten++;
            }

            int bendingRuntimeWritten = 0;
            foreach (BendingRuntimeCase runtimeCase in BendingRuntimeCases())
            {
                BendingRuntimeDump dump = RunBendingRuntimeCase(runtimeCase);
                string json = BuildBendingRuntimeJson(runtimeCase, dump);
                string path = Path.Combine(outputDirectory, runtimeCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                bendingRuntimeWritten++;
            }

            int parameterWritten = WriteParameterFixtures(outputDirectory);
            int frameWritten = WriteFrameFixtures(outputDirectory);
            int centerWritten = WriteCenterFixtures(outputDirectory);
            int centerStepWritten = WriteCenterStepFixtures(outputDirectory);
            int centerFrameShiftWritten = WriteCenterFrameShiftFixtures(outputDirectory);
            int particleStepWritten = WriteParticleStepFixtures(outputDirectory);

            Debug.Log(
                $"[MC2 Oracle] PASS: {written} Tier A Mesh baseline fixtures, "
                + $"{proxyWritten} proxy fixtures, {distanceWritten} distance fixtures, "
                + $"{distanceRuntimeWritten} distance runtime fixtures, "
                + $"{bendingWritten} bending fixtures, "
                + $"{bendingRuntimeWritten} bending runtime fixtures, "
                + $"{parameterWritten} runtime parameter fixtures, "
                + $"{frameWritten} frame/reset fixtures, "
                + $"{centerWritten} center fixtures, "
                + $"{centerStepWritten} center-step fixtures, "
                + $"{centerFrameShiftWritten} center-frame-shift fixtures, "
                + $"{particleStepWritten} particle-step fixtures"
            );
        }

        private static int WriteParticleStepFixtures(string outputDirectory)
        {
            ParticleStepDump dump = RunParticleStepOracle();
            string path = Path.Combine(outputDirectory, "particle_step_gravity_damping_001.json");
            File.WriteAllText(path, BuildParticleStepJson(dump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            ParticleInertiaStepDump inertiaDump = RunParticleInertiaStepOracle();
            path = Path.Combine(outputDirectory, "particle_step_inertia_001.json");
            File.WriteAllText(path, BuildParticleInertiaStepJson(inertiaDump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            BaselineStepPoseDump baselineDump = RunBaselineStepPoseOracle();
            path = Path.Combine(outputDirectory, "particle_step_baseline_pose_001.json");
            File.WriteAllText(path, BuildBaselineStepPoseJson(baselineDump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            return 3;
        }

        private static BaselineStepPoseDump RunBaselineStepPoseOracle()
        {
            MethodInfo method = typeof(SimulationManager).GetMethod(
                "SimulationStepUpdateBaseLinePose",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(SimulationManager).FullName,
                    "SimulationStepUpdateBaseLinePose"
                );
            }
            var team = new TeamManager.TeamData
            {
                particleChunk = new DataChunk(0, 4),
                proxyCommonChunk = new DataChunk(0, 4),
                baseLineChunk = new DataChunk(0, 1),
                baseLineDataChunk = new DataChunk(0, 3),
                initScale = new float3(2.0f, 1.0f, 0.5f),
                scaleRatio = 1.5f,
                negativeScaleDirection = new float3(1.0f),
                negativeScaleQuaternionValue = new float4(1.0f),
                animationPoseRatio = 0.25f,
            };
            var attributes = new NativeArray<VertexAttribute>(
                new[]
                {
                    new VertexAttribute(1), new VertexAttribute(2),
                    new VertexAttribute(2), new VertexAttribute(2),
                },
                Allocator.TempJob
            );
            var parents = new NativeArray<int>(new[] { -1, 0, 1, -1 }, Allocator.TempJob);
            var baselineStarts = new NativeArray<ushort>(new ushort[] { 0 }, Allocator.TempJob);
            var baselineCounts = new NativeArray<ushort>(new ushort[] { 3 }, Allocator.TempJob);
            var baselineData = new NativeArray<ushort>(new ushort[] { 0, 1, 2 }, Allocator.TempJob);
            var localPositions = new NativeArray<float3>(
                new[]
                {
                    float3.zero, new float3(1.0f, 0.0f, 0.0f),
                    new float3(0.0f, 1.0f, 0.0f), float3.zero,
                },
                Allocator.TempJob
            );
            var localRotations = new NativeArray<quaternion>(
                new[]
                {
                    quaternion.identity,
                    quaternion.AxisAngle(math.forward(), math.radians(30.0f)),
                    quaternion.AxisAngle(math.right(), math.radians(20.0f)),
                    quaternion.identity,
                },
                Allocator.TempJob
            );
            var basePositions = new NativeArray<float3>(
                new[]
                {
                    new float3(10.0f, 0.0f, 0.0f),
                    new float3(12.0f, 4.0f, 0.0f),
                    new float3(-1.0f, 8.0f, 2.0f),
                    new float3(7.0f, 7.0f, 7.0f),
                },
                Allocator.TempJob
            );
            var baseRotations = new NativeArray<quaternion>(
                new[]
                {
                    quaternion.AxisAngle(math.up(), math.radians(10.0f)),
                    quaternion.AxisAngle(math.up(), math.radians(80.0f)),
                    quaternion.AxisAngle(math.forward(), math.radians(-25.0f)),
                    quaternion.AxisAngle(math.right(), math.radians(15.0f)),
                },
                Allocator.TempJob
            );
            var stepPositions = new NativeArray<float3>(basePositions.ToArray(), Allocator.TempJob);
            var stepRotations = new NativeArray<quaternion>(baseRotations.ToArray(), Allocator.TempJob);
            try
            {
                object[] arguments =
                {
                    new DataChunk(0, 1), team, attributes, parents,
                    baselineStarts, baselineCounts, baselineData,
                    localPositions, localRotations,
                    basePositions, baseRotations, stepPositions, stepRotations,
                };
                InvokeStatic(method, arguments);
                return new BaselineStepPoseDump
                {
                    StepBasicPositions = stepPositions.ToArray(),
                    StepBasicRotations = stepRotations.ToArray(),
                };
            }
            finally
            {
                attributes.Dispose(); parents.Dispose(); baselineStarts.Dispose();
                baselineCounts.Dispose(); baselineData.Dispose(); localPositions.Dispose();
                localRotations.Dispose(); basePositions.Dispose(); baseRotations.Dispose();
                stepPositions.Dispose(); stepRotations.Dispose();
            }
        }

        private static int WriteCenterFixtures(string outputDirectory)
        {
            CenterStaticDump dump = RunCenterStaticOracle();
            string path = Path.Combine(outputDirectory, "center_static_fixed_001.json");
            File.WriteAllText(path, BuildCenterStaticJson(dump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            return 1;
        }

        private static int WriteCenterStepFixtures(string outputDirectory)
        {
            CenterStepDump dump = RunCenterStepOracle();
            string path = Path.Combine(outputDirectory, "center_step_inertia_001.json");
            File.WriteAllText(path, BuildCenterStepJson(dump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            return 1;
        }

        private static int WriteCenterFrameShiftFixtures(string outputDirectory)
        {
            CenterFrameShiftDump worldInertia = RunCenterFrameShiftOracle(
                0.25f,
                0.0f,
                -1.0f,
                -1.0f,
                float3.zero,
                false,
                0.1f,
                0.1f,
                1.0f,
                0,
                false
            );
            string worldInertiaPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_world_inertia_001.json"
            );
            File.WriteAllText(
                worldInertiaPath,
                BuildCenterFrameShiftJson(
                    "center_frame_shift_world_inertia_001",
                    "Isolates positive-scale world-inertia frame shift with no fixed list, anchor, smoothing, speed limits, teleport, synchronization, culling, skip, or stabilization effects.",
                    -1.0f,
                    -1.0f,
                    worldInertia
                ),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {worldInertiaPath}");

            CenterFrameShiftDump speedLimit = RunCenterFrameShiftOracle(
                0.25f,
                0.0f,
                10.0f,
                90.0f,
                float3.zero,
                false,
                0.1f,
                0.1f,
                1.0f,
                0,
                false
            );
            string speedLimitPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_speed_limit_001.json"
            );
            File.WriteAllText(
                speedLimitPath,
                BuildCenterFrameShiftJson(
                    "center_frame_shift_speed_limit_001",
                    "Isolates movement and rotation speed-limit cancellation after positive-scale world-inertia shift, with no fixed list, anchor, smoothing, teleport, synchronization, culling, skip, or stabilization effects.",
                    10.0f,
                    90.0f,
                    speedLimit
                ),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {speedLimitPath}");

            CenterFrameShiftDump anchor = RunCenterAnchorShiftOracle(1.0f, -1.0f, -1.0f);
            string anchorPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_anchor_001.json"
            );
            File.WriteAllText(
                anchorPath,
                BuildCenterAnchorShiftJson(
                    "center_frame_shift_anchor_001",
                    "Isolates positive-scale anchor cancellation with world inertia, fixed list, smoothing, speed limits, teleport, synchronization, culling, skip, and stabilization disabled.",
                    1.0f,
                    -1.0f,
                    -1.0f,
                    anchor
                ),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {anchorPath}");

            CenterFrameShiftDump anchorWorldLimit = RunCenterAnchorShiftOracle(
                0.25f,
                0.5f,
                90.0f
            );
            string anchorWorldLimitPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_anchor_world_limit_001.json"
            );
            File.WriteAllText(
                anchorWorldLimitPath,
                BuildCenterAnchorShiftJson(
                    "center_frame_shift_anchor_world_limit_001",
                    "Isolates positive-scale anchor cancellation followed by world inertia and movement/rotation speed limits, with no fixed list, smoothing, teleport, synchronization, culling, skip, or stabilization effects.",
                    0.25f,
                    0.5f,
                    90.0f,
                    anchorWorldLimit
                ),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {anchorWorldLimitPath}");

            CenterFrameShiftDump smoothing = RunCenterFrameShiftOracle(
                1.0f,
                0.5f,
                -1.0f,
                -1.0f,
                new float3(2.0f, 0.0f, 0.0f),
                true,
                0.1f,
                0.1f,
                1.0f,
                0,
                false
            );
            string smoothingPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_smoothing_001.json"
            );
            File.WriteAllText(
                smoothingPath,
                BuildCenterSmoothingShiftJson(smoothing),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {smoothingPath}");

            CenterFrameShiftDump timeScale = RunCenterFrameShiftOracle(
                0.75f,
                0.0f,
                -1.0f,
                -1.0f,
                float3.zero,
                false,
                0.05f,
                0.1f,
                0.5f,
                0,
                false
            );
            string timeScalePath = Path.Combine(
                outputDirectory,
                "center_frame_shift_time_scale_001.json"
            );
            File.WriteAllText(
                timeScalePath,
                BuildCenterTimeScaleShiftJson(timeScale),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {timeScalePath}");

            CenterFrameShiftDump skipCount = RunCenterFrameShiftOracle(
                1.0f,
                0.0f,
                -1.0f,
                -1.0f,
                float3.zero,
                true,
                0.02f,
                0.1f,
                1.0f,
                2,
                false
            );
            string skipCountPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_skip_count_001.json"
            );
            File.WriteAllText(
                skipCountPath,
                BuildCenterSkipCountShiftJson(skipCount),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {skipCountPath}");

            CenterFrameShiftDump fixedCenter = RunCenterFrameShiftOracle(
                0.25f,
                0.0f,
                -1.0f,
                -1.0f,
                float3.zero,
                false,
                0.1f,
                0.1f,
                1.0f,
                0,
                true
            );
            string fixedCenterPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_fixed_center_001.json"
            );
            File.WriteAllText(
                fixedCenterPath,
                BuildCenterFixedShiftJson(fixedCenter),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {fixedCenterPath}");

            CenterFrameShiftDump zeroTimeScale = RunCenterFrameShiftOracle(
                0.75f,
                0.0f,
                -1.0f,
                -1.0f,
                float3.zero,
                false,
                0.0f,
                0.1f,
                0.0f,
                0,
                false
            );
            string zeroTimeScalePath = Path.Combine(
                outputDirectory,
                "center_frame_shift_zero_time_scale_001.json"
            );
            File.WriteAllText(
                zeroTimeScalePath,
                BuildCenterZeroTimeScaleShiftJson(zeroTimeScale),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {zeroTimeScalePath}");

            CenterFrameShiftDump keepTeleport = RunCenterFrameShiftOracle(
                1.0f,
                0.5f,
                -1.0f,
                -1.0f,
                new float3(2.0f, 0.0f, 0.0f),
                true,
                0.1f,
                0.1f,
                1.0f,
                0,
                false,
                InertiaConstraint.TeleportMode.Keep,
                5.0f,
                180.0f
            );
            string keepTeleportPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_keep_teleport_001.json"
            );
            File.WriteAllText(
                keepTeleportPath,
                BuildCenterKeepTeleportJson(keepTeleport),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {keepTeleportPath}");

            CenterFrameShiftDump resetTeleport = RunCenterFrameShiftOracle(
                1.0f,
                0.5f,
                -1.0f,
                -1.0f,
                new float3(2.0f, 0.0f, 0.0f),
                true,
                0.1f,
                0.1f,
                1.0f,
                0,
                false,
                InertiaConstraint.TeleportMode.Reset,
                5.0f,
                180.0f
            );
            string resetTeleportPath = Path.Combine(
                outputDirectory,
                "center_frame_shift_reset_teleport_001.json"
            );
            File.WriteAllText(
                resetTeleportPath,
                BuildCenterResetTeleportJson(resetTeleport),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {resetTeleportPath}");

            NegativeScaleTeleportDump resetNegativeScale =
                RunNegativeScaleTeleportOracle(InertiaConstraint.TeleportMode.Reset);
            string resetNegativeScalePath = Path.Combine(
                outputDirectory,
                "center_frame_shift_reset_negative_scale_x_001.json"
            );
            File.WriteAllText(
                resetNegativeScalePath,
                BuildResetNegativeScaleTeleportJson(resetNegativeScale),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {resetNegativeScalePath}");

            NegativeScaleTeleportDump negativeScale = RunNegativeScaleTeleportOracle();
            string negativeScalePath = Path.Combine(
                outputDirectory,
                "center_frame_shift_negative_scale_x_001.json"
            );
            File.WriteAllText(
                negativeScalePath,
                BuildNegativeScaleTeleportJson(negativeScale),
                new UTF8Encoding(false)
            );
            Debug.Log($"[MC2 Oracle] wrote {negativeScalePath}");
            return 13;
        }

        private static NegativeScaleTeleportDump RunNegativeScaleTeleportOracle(
            InertiaConstraint.TeleportMode teleportMode = InertiaConstraint.TeleportMode.None
        )
        {
            MethodInfo centerMethod = typeof(TeamManager).GetMethod(
                "SimulationCalcCenterAndInertiaAndWind",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            MethodInfo particleMethod = typeof(SimulationManager).GetMethod(
                "SimulationPreTeamUpdate",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (centerMethod == null || particleMethod == null)
            {
                throw new MissingMethodException("MC2 negative-scale oracle producer is unavailable");
            }

            var team = new TeamManager.TeamData
            {
                frameDeltaTime = 0.1f,
                nowTimeScale = 1.0f,
                updateCount = 1,
                particleChunk = new DataChunk(0, 1),
                proxyCommonChunk = new DataChunk(0, 1),
                initScale = new float3(1.0f),
                negativeScaleSign = 1.0f,
                negativeScaleDirection = new float3(1.0f),
                negativeScaleChange = new float3(1.0f),
                negativeScaleTriangleSign = new float2(1.0f),
                negativeScaleQuaternionValue = new float4(1.0f),
                velocityWeight = 1.0f,
            };
            var parameters = new ClothParameters
            {
                inertiaConstraint = new InertiaConstraint.InertiaConstraintParams
                {
                    worldInertia = 1.0f,
                    movementInertiaSmoothing = 0.0f,
                    movementSpeedLimit = -1.0f,
                    rotationSpeedLimit = -1.0f,
                    teleportMode = teleportMode,
                    teleportDistance = 1000.0f,
                    teleportRotation = 30.0f,
                },
            };
            var center = new InertiaConstraint.CenterData
            {
                centerTransformIndex = 0,
                oldComponentWorldPosition = new float3(1.0f, 2.0f, 3.0f),
                oldComponentWorldRotation = quaternion.AxisAngle(math.up(), math.radians(20.0f)),
                oldComponentWorldScale = new float3(1.0f, 2.0f, 0.5f),
                oldFrameWorldPosition = new float3(-2.0f, 1.0f, 4.0f),
                oldFrameWorldRotation = quaternion.AxisAngle(math.up(), math.radians(-30.0f)),
                oldFrameWorldScale = new float3(1.0f, 2.0f, 0.5f),
                nowWorldPosition = new float3(0.5f, -1.0f, 2.0f),
                nowWorldRotation = quaternion.AxisAngle(math.right(), math.radians(15.0f)),
                oldWorldPosition = new float3(0.5f, -1.0f, 2.0f),
                oldWorldRotation = quaternion.AxisAngle(math.right(), math.radians(15.0f)),
                oldAnchorPosition = new float3(2.0f, -3.0f, 1.0f),
                smoothingVelocity = new float3(1.0f, 2.0f, -1.0f),
            };
            var wind = new TeamWindData();
            var positions = new NativeArray<float3>(new[] { new float3(8.0f, 1.0f, -2.0f) }, Allocator.TempJob);
            var rotations = new NativeArray<quaternion>(new[] { quaternion.identity }, Allocator.TempJob);
            var bindRotations = new NativeArray<quaternion>(new[] { quaternion.identity }, Allocator.TempJob);
            var fixedIndices = new NativeArray<ushort>(0, Allocator.TempJob);
            var transformPositions = new NativeArray<float3>(new[] { new float3(4.0f, -2.0f, 5.0f) }, Allocator.TempJob);
            var transformRotations = new NativeArray<quaternion>(
                new[] { quaternion.AxisAngle(math.up(), math.radians(65.0f)) },
                Allocator.TempJob
            );
            var transformScales = new NativeArray<float3>(new[] { new float3(-2.0f, 1.5f, 0.75f) }, Allocator.TempJob);
            var windData = new NativeArray<WindManager.WindData>(0, Allocator.TempJob);
            var depths = new NativeArray<float>(new[] { 0.5f }, Allocator.TempJob);
            var next = new NativeArray<float3>(new[] { new float3(100.0f) }, Allocator.TempJob);
            var old = new NativeArray<float3>(new[] { new float3(2.0f, 3.0f, 4.0f) }, Allocator.TempJob);
            var oldRot = new NativeArray<quaternion>(
                new[] { quaternion.AxisAngle(math.up(), math.radians(30.0f)) },
                Allocator.TempJob
            );
            var basePos = new NativeArray<float3>(new[] { new float3(101.0f) }, Allocator.TempJob);
            var baseRot = new NativeArray<quaternion>(new[] { quaternion.identity }, Allocator.TempJob);
            var animationOld = new NativeArray<float3>(new[] { new float3(5.0f, -1.0f, 2.0f) }, Allocator.TempJob);
            var animationOldRot = new NativeArray<quaternion>(
                new[] { quaternion.AxisAngle(math.right(), math.radians(45.0f)) },
                Allocator.TempJob
            );
            var velocityReference = new NativeArray<float3>(new[] { new float3(102.0f) }, Allocator.TempJob);
            var display = new NativeArray<float3>(new[] { new float3(-2.0f, 1.0f, 3.0f) }, Allocator.TempJob);
            var velocity = new NativeArray<float3>(new[] { new float3(1.0f, 2.0f, -1.0f) }, Allocator.TempJob);
            var realVelocity = new NativeArray<float3>(new[] { new float3(-1.0f, 0.5f, 2.0f) }, Allocator.TempJob);
            var friction = new NativeArray<float>(1, Allocator.TempJob);
            var staticFriction = new NativeArray<float>(1, Allocator.TempJob);
            var collisionNormal = new NativeArray<float3>(1, Allocator.TempJob);
            try
            {
                object[] centerArguments =
                {
                    0.1f, 0, team, center, wind, parameters,
                    positions, rotations, bindRotations, fixedIndices,
                    transformPositions, transformRotations, transformScales,
                    0, windData,
                };
                InvokeStatic(centerMethod, centerArguments);
                team = (TeamManager.TeamData)centerArguments[2];
                center = (InertiaConstraint.CenterData)centerArguments[3];

                object[] particleArguments =
                {
                    new DataChunk(0, 1), team, parameters, center,
                    positions, rotations, depths,
                    next, old, oldRot, basePos, baseRot,
                    animationOld, animationOldRot, velocityReference, display,
                    velocity, realVelocity, friction, staticFriction, collisionNormal,
                };
                InvokeStatic(particleMethod, particleArguments);
                return new NegativeScaleTeleportDump
                {
                    KeepTeleport = team.IsKeepReset,
                    Reset = team.IsReset,
                    InertiaShift = team.IsInertiaShift,
                    NegativeScaleTeleport = team.IsNegativeScaleTeleport,
                    NegativeScaleSign = team.negativeScaleSign,
                    NegativeScaleDirection = team.negativeScaleDirection,
                    NegativeScaleChange = team.negativeScaleChange,
                    NegativeScaleTriangleSign = team.negativeScaleTriangleSign,
                    NegativeScaleQuaternionValue = team.negativeScaleQuaternionValue,
                    NegativeScaleMatrix = center.negativeScaleMatrix,
                    OldComponentWorldPosition = center.oldComponentWorldPosition,
                    OldComponentWorldScale = center.oldComponentWorldScale,
                    OldAnchorPosition = center.oldAnchorPosition,
                    SmoothingVelocity = center.smoothingVelocity,
                    OldPosition = old[0],
                    OldRotation = oldRot[0],
                    AnimationOldPosition = animationOld[0],
                    AnimationOldRotation = animationOldRot[0],
                    DisplayPosition = display[0],
                    Velocity = velocity[0],
                    RealVelocity = realVelocity[0],
                    FrameComponentShiftVector = center.frameComponentShiftVector,
                    FrameComponentShiftRotation = center.frameComponentShiftRotation,
                    OldFrameWorldPosition = center.oldFrameWorldPosition,
                    OldFrameWorldRotation = center.oldFrameWorldRotation,
                    NowWorldPosition = center.nowWorldPosition,
                    NowWorldRotation = center.nowWorldRotation,
                    FrameWorldPosition = center.frameWorldPosition,
                    FrameWorldRotation = center.frameWorldRotation,
                    NextPosition = next[0],
                    BasePosition = basePos[0],
                    BaseRotation = baseRot[0],
                    VelocityReferencePosition = velocityReference[0],
                    Friction = friction[0],
                    StaticFriction = staticFriction[0],
                    CollisionNormal = collisionNormal[0],
                };
            }
            finally
            {
                positions.Dispose(); rotations.Dispose(); bindRotations.Dispose(); fixedIndices.Dispose();
                transformPositions.Dispose(); transformRotations.Dispose(); transformScales.Dispose(); windData.Dispose();
                depths.Dispose(); next.Dispose(); old.Dispose(); oldRot.Dispose(); basePos.Dispose(); baseRot.Dispose();
                animationOld.Dispose(); animationOldRot.Dispose(); velocityReference.Dispose(); display.Dispose();
                velocity.Dispose(); realVelocity.Dispose(); friction.Dispose(); staticFriction.Dispose(); collisionNormal.Dispose();
            }
        }

        private static CenterFrameShiftDump RunCenterFrameShiftOracle(
            float worldInertia,
            float movementInertiaSmoothing,
            float movementSpeedLimit,
            float rotationSpeedLimit,
            float3 smoothingVelocity,
            bool isRunning,
            float simulationDeltaTime,
            float frameDeltaTime,
            float nowTimeScale,
            int skipCount,
            bool useFixedCenter,
            InertiaConstraint.TeleportMode teleportMode = InertiaConstraint.TeleportMode.None,
            float teleportDistance = 0.5f,
            float teleportRotation = 90.0f
        )
        {
            MethodInfo method = typeof(TeamManager).GetMethod(
                "SimulationCalcCenterAndInertiaAndWind",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(TeamManager).FullName,
                    "SimulationCalcCenterAndInertiaAndWind"
                );
            }

            var team = skipCount > 0
                ? RunTeamScheduleOracle(
                    frameDeltaTime,
                    nowTimeScale,
                    simulationDeltaTime,
                    3
                )
                : new TeamManager.TeamData
                {
                    frameDeltaTime = frameDeltaTime,
                    nowTimeScale = nowTimeScale,
                    updateCount = 1,
                    skipCount = 0,
                };
            team.proxyCommonChunk = useFixedCenter
                ? new DataChunk(0, 1)
                : default;
            team.fixedDataChunk = useFixedCenter
                ? new DataChunk(0, 1)
                : default;
            team.initScale = new float3(1.0f);
            team.negativeScaleSign = 1.0f;
            team.negativeScaleDirection = new float3(1.0f);
            team.negativeScaleChange = new float3(1.0f);
            team.negativeScaleTriangleSign = new float2(1.0f);
            team.negativeScaleQuaternionValue = new float4(1.0f);
            team.velocityWeight = 1.0f;
            if (isRunning)
                team.flag.SetBits(TeamManager.Flag_Running, true);
            var parameters = new ClothParameters
            {
                inertiaConstraint = new InertiaConstraint.InertiaConstraintParams
                {
                    worldInertia = worldInertia,
                    movementInertiaSmoothing = movementInertiaSmoothing,
                    movementSpeedLimit = movementSpeedLimit,
                    rotationSpeedLimit = rotationSpeedLimit,
                    teleportMode = teleportMode,
                    teleportDistance = teleportDistance,
                    teleportRotation = teleportRotation,
                },
            };
            var center = new InertiaConstraint.CenterData
            {
                centerTransformIndex = 0,
                oldComponentWorldPosition = new float3(0.0f),
                oldComponentWorldRotation = quaternion.identity,
                oldComponentWorldScale = new float3(1.0f),
                oldFrameWorldPosition = new float3(1.0f, 0.0f, 0.0f),
                oldFrameWorldRotation = quaternion.identity,
                oldFrameWorldScale = new float3(1.0f),
                nowWorldPosition = new float3(2.0f, 0.0f, 0.0f),
                nowWorldRotation = quaternion.identity,
                oldWorldPosition = new float3(2.0f, 0.0f, 0.0f),
                oldWorldRotation = quaternion.identity,
                smoothingVelocity = smoothingVelocity,
            };
            var wind = new TeamWindData();
            var positions = new NativeArray<float3>(useFixedCenter ? 1 : 0, Allocator.TempJob);
            var rotations = new NativeArray<quaternion>(useFixedCenter ? 1 : 0, Allocator.TempJob);
            var bindRotations = new NativeArray<quaternion>(useFixedCenter ? 1 : 0, Allocator.TempJob);
            var fixedIndices = new NativeArray<ushort>(useFixedCenter ? 1 : 0, Allocator.TempJob);
            if (useFixedCenter)
            {
                positions[0] = new float3(12.0f, 2.0f, 0.0f);
                rotations[0] = quaternion.AxisAngle(math.up(), math.radians(90.0f));
                bindRotations[0] = quaternion.identity;
                fixedIndices[0] = 0;
            }
            var transformPositions = new NativeArray<float3>(
                new[] { new float3(10.0f, 0.0f, 0.0f) },
                Allocator.TempJob
            );
            var transformRotations = new NativeArray<quaternion>(
                new[] { quaternion.AxisAngle(math.up(), math.radians(90.0f)) },
                Allocator.TempJob
            );
            var transformScales = new NativeArray<float3>(
                new[] { new float3(1.0f) },
                Allocator.TempJob
            );
            var windData = new NativeArray<WindManager.WindData>(0, Allocator.TempJob);
            try
            {
                object[] arguments =
                {
                    simulationDeltaTime,
                    0,
                    team,
                    center,
                    wind,
                    parameters,
                    positions,
                    rotations,
                    bindRotations,
                    fixedIndices,
                    transformPositions,
                    transformRotations,
                    transformScales,
                    0,
                    windData,
                };
                InvokeStatic(method, arguments);
                team = (TeamManager.TeamData)arguments[2];
                center = (InertiaConstraint.CenterData)arguments[3];
                float[] stepFrameInterpolations = Array.Empty<float>();
                if (skipCount > 0)
                {
                    MethodInfo stepMethod = typeof(TeamManager).GetMethod(
                        "SimulationStepTeamUpdate",
                        BindingFlags.Static | BindingFlags.NonPublic
                    );
                    if (stepMethod == null)
                        throw new MissingMethodException(
                            typeof(TeamManager).FullName,
                            "SimulationStepTeamUpdate"
                        );
                    var stepTeam = team;
                    var stepParameters = parameters;
                    var stepCenter = center;
                    var stepWind = new TeamWindData();
                    stepFrameInterpolations = new float[team.updateCount];
                    for (int updateIndex = 0; updateIndex < team.updateCount; updateIndex++)
                    {
                        object[] stepArguments =
                        {
                            updateIndex, simulationDeltaTime, 0,
                            stepTeam, stepParameters, stepCenter, stepWind,
                        };
                        InvokeStatic(stepMethod, stepArguments);
                        stepTeam = (TeamManager.TeamData)stepArguments[3];
                        stepParameters = (ClothParameters)stepArguments[4];
                        stepCenter = (InertiaConstraint.CenterData)stepArguments[5];
                        stepWind = (TeamWindData)stepArguments[6];
                        stepFrameInterpolations[updateIndex] = stepTeam.frameInterpolation;
                    }
                }
                return new CenterFrameShiftDump
                {
                    KeepTeleport = team.IsKeepReset,
                    Reset = team.IsReset,
                    UpdateCount = team.updateCount,
                    SkipCount = team.skipCount,
                    Time = team.time,
                    OldTime = team.oldTime,
                    NowUpdateTime = team.nowUpdateTime,
                    OldUpdateTime = team.oldUpdateTime,
                    FrameUpdateTime = team.frameUpdateTime,
                    FrameOldTime = team.frameOldTime,
                    StepFrameInterpolations = stepFrameInterpolations,
                    FrameComponentShiftVector = center.frameComponentShiftVector,
                    FrameComponentShiftRotation = center.frameComponentShiftRotation,
                    OldFrameWorldPosition = center.oldFrameWorldPosition,
                    OldFrameWorldRotation = center.oldFrameWorldRotation,
                    NowWorldPosition = center.nowWorldPosition,
                    NowWorldRotation = center.nowWorldRotation,
                    FrameWorldPosition = center.frameWorldPosition,
                    FrameWorldRotation = center.frameWorldRotation,
                    FrameMovingDirection = center.frameMovingDirection,
                    FrameMovingSpeed = center.frameMovingSpeed,
                    SmoothingVelocity = center.smoothingVelocity,
                };
            }
            finally
            {
                positions.Dispose();
                rotations.Dispose();
                bindRotations.Dispose();
                fixedIndices.Dispose();
                transformPositions.Dispose();
                transformRotations.Dispose();
                transformScales.Dispose();
                windData.Dispose();
            }
        }

        private static TeamManager.TeamData RunTeamScheduleOracle(
            float frameDeltaTime,
            float globalTimeScale,
            float simulationDeltaTime,
            int maxSimulationCountPerFrame
        )
        {
            Type jobType = typeof(TeamManager).GetNestedType(
                "AlwaysTeamUpdatePostJob",
                BindingFlags.NonPublic
            );
            if (jobType == null)
                throw new MissingMemberException("MC2 scheduler job is unavailable");
            object job = Activator.CreateInstance(jobType);
            void Set(string name, object value)
            {
                FieldInfo field = jobType.GetField(
                    name,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                );
                if (field == null)
                    throw new MissingFieldException(jobType.FullName, name);
                field.SetValue(job, value);
            }

            var teamStatus = new NativeReference<int4>(Allocator.TempJob);
            var teams = new NativeArray<TeamManager.TeamData>(2, Allocator.TempJob);
            var parameters = new NativeArray<ClothParameters>(2, Allocator.TempJob);
            var centers = new NativeArray<InertiaConstraint.CenterData>(2, Allocator.TempJob);
            var componentPositions = new NativeArray<float3>(1, Allocator.TempJob);
            var componentMinScales = new NativeArray<float>(1, Allocator.TempJob);
            var syncTeams = new NativeParallelHashMap<MagicaObjectId, int>(1, Allocator.TempJob);
            var syncTops = new NativeParallelHashMap<MagicaObjectId, MagicaObjectId>(1, Allocator.TempJob);
            var animatorModes = new NativeParallelHashMap<MagicaObjectId, int>(1, Allocator.TempJob);
            var anchorIndices = new NativeArray<MagicaObjectId>(2, Allocator.TempJob);
            var distanceIndices = new NativeArray<MagicaObjectId>(2, Allocator.TempJob);
            var transformPositions = new NativeParallelHashMap<MagicaObjectId, float3>(1, Allocator.TempJob);
            var transformRotations = new NativeParallelHashMap<MagicaObjectId, quaternion>(1, Allocator.TempJob);
            var cullingDirty = new NativeList<int>(Allocator.TempJob);
            var normalTeams = new NativeList<int>(Allocator.TempJob);
            var splitTeams = new NativeList<int>(Allocator.TempJob);
            try
            {
                var team = new TeamManager.TeamData
                {
                    originalUpdateMode = ClothUpdateMode.Normal,
                    updateMode = ClothUpdateMode.Normal,
                    timeScale = 1.0f,
                    componentTransformIndex = 0,
                    initScale = new float3(1.0f),
                    negativeScaleSign = 1.0f,
                    negativeScaleDirection = new float3(1.0f),
                    negativeScaleChange = new float3(1.0f),
                    negativeScaleTriangleSign = new float2(1.0f),
                    negativeScaleQuaternionValue = new float4(1.0f),
                    velocityWeight = 1.0f,
                    distanceWeight = 1.0f,
                };
                team.flag.SetBits(TeamManager.Flag_Valid, true);
                team.flag.SetBits(TeamManager.Flag_Enable, true);
                team.flag.SetBits(TeamManager.Flag_TimeReset, true);
                teams[1] = team;
                componentMinScales[0] = 1.0f;

                Set("teamCount", 2);
                Set("unityFrameDeltaTime", frameDeltaTime);
                Set("unityFrameFixedDeltaTime", frameDeltaTime);
                Set("unityFrameUnscaledDeltaTime", frameDeltaTime);
                Set("globalTimeScale", globalTimeScale);
                Set("simulationDeltaTime", simulationDeltaTime);
                Set("maxSimmulationCountPerFrame", maxSimulationCountPerFrame);
                Set("splitProxyMeshVertexCount", 1);
                Set("teamStatus", teamStatus);
                Set("teamDataArray", teams);
                Set("parameterArray", parameters);
                Set("centerDataArray", centers);
                Set("componentPositionArray", componentPositions);
                Set("componentMinScaleArray", componentMinScales);
                Set("hasMainCamera", true);
                Set("comp2TeamIdMap", syncTeams);
                Set("comp2SyncTopCompMap", syncTops);
                Set("animatorUpdateModeMap", animatorModes);
                Set("teamAnchorTransformIndexArray", anchorIndices);
                Set("teamDistanceTransformIndexArray", distanceIndices);
                Set("transformPositionMap", transformPositions);
                Set("transformRotationMap", transformRotations);
                Set("cullingDirtyList", cullingDirty);
                Set("batchNormalClothTeamList", normalTeams);
                Set("batchSplitClothTeamList", splitTeams);

                MethodInfo execute = jobType.GetMethod(
                    "Execute",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                );
                if (execute == null)
                    throw new MissingMethodException(jobType.FullName, "Execute");
                execute.Invoke(job, null);
                return teams[1];
            }
            finally
            {
                teamStatus.Dispose(); teams.Dispose(); parameters.Dispose(); centers.Dispose();
                componentPositions.Dispose(); componentMinScales.Dispose(); syncTeams.Dispose();
                syncTops.Dispose(); animatorModes.Dispose(); anchorIndices.Dispose(); distanceIndices.Dispose();
                transformPositions.Dispose(); transformRotations.Dispose(); cullingDirty.Dispose();
                normalTeams.Dispose(); splitTeams.Dispose();
            }
        }

        private static CenterFrameShiftDump RunCenterAnchorShiftOracle(
            float worldInertia,
            float movementSpeedLimit,
            float rotationSpeedLimit
        )
        {
            MethodInfo method = typeof(TeamManager).GetMethod(
                "SimulationCalcCenterAndInertiaAndWind",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(TeamManager).FullName,
                    "SimulationCalcCenterAndInertiaAndWind"
                );
            }

            var team = new TeamManager.TeamData
            {
                frameDeltaTime = 0.1f,
                nowTimeScale = 1.0f,
                updateCount = 1,
                initScale = new float3(1.0f),
                negativeScaleSign = 1.0f,
                negativeScaleDirection = new float3(1.0f),
                negativeScaleChange = new float3(1.0f),
                negativeScaleTriangleSign = new float2(1.0f),
                negativeScaleQuaternionValue = new float4(1.0f),
                velocityWeight = 1.0f,
            };
            team.flag.SetBits(TeamManager.Flag_Anchor, true);
            var parameters = new ClothParameters
            {
                inertiaConstraint = new InertiaConstraint.InertiaConstraintParams
                {
                    anchorInertia = 0.25f,
                    worldInertia = worldInertia,
                    movementInertiaSmoothing = 0.0f,
                    movementSpeedLimit = movementSpeedLimit,
                    rotationSpeedLimit = rotationSpeedLimit,
                    teleportMode = InertiaConstraint.TeleportMode.None,
                },
            };
            var center = new InertiaConstraint.CenterData
            {
                centerTransformIndex = 0,
                oldComponentWorldPosition = new float3(1.0f, 0.0f, 0.0f),
                oldComponentWorldRotation = quaternion.identity,
                oldComponentWorldScale = new float3(1.0f),
                oldFrameWorldPosition = new float3(1.0f, 0.0f, 0.0f),
                oldFrameWorldRotation = quaternion.identity,
                oldFrameWorldScale = new float3(1.0f),
                nowWorldPosition = new float3(1.0f, 0.0f, 0.0f),
                nowWorldRotation = quaternion.identity,
                oldWorldPosition = new float3(1.0f, 0.0f, 0.0f),
                oldWorldRotation = quaternion.identity,
                anchorPosition = new float3(0.0f, 0.0f, 1.0f),
                anchorRotation = quaternion.AxisAngle(math.up(), math.radians(90.0f)),
                oldAnchorPosition = new float3(0.0f),
                oldAnchorRotation = quaternion.identity,
                anchorComponentLocalPosition = new float3(1.0f, 0.0f, 0.0f),
            };
            var wind = new TeamWindData();
            var positions = new NativeArray<float3>(0, Allocator.TempJob);
            var rotations = new NativeArray<quaternion>(0, Allocator.TempJob);
            var bindRotations = new NativeArray<quaternion>(0, Allocator.TempJob);
            var fixedIndices = new NativeArray<ushort>(0, Allocator.TempJob);
            var transformPositions = new NativeArray<float3>(
                new[] { new float3(0.0f) },
                Allocator.TempJob
            );
            var transformRotations = new NativeArray<quaternion>(
                new[] { quaternion.AxisAngle(math.up(), math.radians(90.0f)) },
                Allocator.TempJob
            );
            var transformScales = new NativeArray<float3>(
                new[] { new float3(1.0f) },
                Allocator.TempJob
            );
            var windData = new NativeArray<WindManager.WindData>(0, Allocator.TempJob);
            try
            {
                object[] arguments =
                {
                    0.1f,
                    0,
                    team,
                    center,
                    wind,
                    parameters,
                    positions,
                    rotations,
                    bindRotations,
                    fixedIndices,
                    transformPositions,
                    transformRotations,
                    transformScales,
                    0,
                    windData,
                };
                InvokeStatic(method, arguments);
                center = (InertiaConstraint.CenterData)arguments[3];
                return new CenterFrameShiftDump
                {
                    FrameComponentShiftVector = center.frameComponentShiftVector,
                    FrameComponentShiftRotation = center.frameComponentShiftRotation,
                    OldFrameWorldPosition = center.oldFrameWorldPosition,
                    OldFrameWorldRotation = center.oldFrameWorldRotation,
                    NowWorldPosition = center.nowWorldPosition,
                    NowWorldRotation = center.nowWorldRotation,
                    FrameWorldPosition = center.frameWorldPosition,
                    FrameWorldRotation = center.frameWorldRotation,
                    FrameMovingDirection = center.frameMovingDirection,
                    FrameMovingSpeed = center.frameMovingSpeed,
                };
            }
            finally
            {
                positions.Dispose();
                rotations.Dispose();
                bindRotations.Dispose();
                fixedIndices.Dispose();
                transformPositions.Dispose();
                transformRotations.Dispose();
                transformScales.Dispose();
                windData.Dispose();
            }
        }

        private static CenterStepDump RunCenterStepOracle()
        {
            MethodInfo method = typeof(TeamManager).GetMethod(
                "SimulationStepTeamUpdate",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(TeamManager).FullName,
                    "SimulationStepTeamUpdate"
                );
            }

            var team = new TeamManager.TeamData
            {
                time = 1.4f,
                frameOldTime = 1.0f,
                nowUpdateTime = 1.1f,
                updateCount = 1,
                initScale = new float3(1.0f),
                negativeScaleDirection = new float3(1.0f, -1.0f, 1.0f),
                velocityWeight = 0.2f,
                distanceWeight = 0.8f,
            };
            var parameters = new ClothParameters
            {
                gravity = 9.0f,
                worldGravityDirection = new float3(1.0f, 0.0f, 0.0f),
                gravityFalloff = 0.6f,
                stablizationTimeAfterReset = 0.5f,
                blendWeight = 0.7f,
                inertiaConstraint = new InertiaConstraint.InertiaConstraintParams
                {
                    localInertia = 0.75f,
                    localMovementSpeedLimit = 5.0f,
                    localRotationSpeedLimit = 90.0f,
                },
            };
            var center = new InertiaConstraint.CenterData
            {
                oldFrameWorldPosition = new float3(0.0f),
                frameWorldPosition = new float3(4.0f, 2.0f, -2.0f),
                oldFrameWorldRotation = quaternion.identity,
                frameWorldRotation = quaternion.AxisAngle(math.up(), math.radians(90.0f)),
                oldFrameWorldScale = new float3(1.0f),
                frameWorldScale = new float3(2.0f, 1.0f, 1.0f),
                nowWorldPosition = new float3(0.0f),
                nowWorldRotation = quaternion.identity,
                oldWorldPosition = new float3(0.0f),
                oldWorldRotation = quaternion.identity,
                initLocalGravityDirection = new float3(1.0f, 0.0f, 0.0f),
            };
            var wind = new TeamWindData();
            object[] arguments = { 0, 0.1f, 1, team, parameters, center, wind };
            InvokeStatic(method, arguments);
            team = (TeamManager.TeamData)arguments[3];
            center = (InertiaConstraint.CenterData)arguments[5];
            return new CenterStepDump
            {
                FrameInterpolation = team.frameInterpolation,
                NowWorldPosition = center.nowWorldPosition,
                NowWorldRotation = center.nowWorldRotation,
                StepVector = center.stepVector,
                StepRotation = center.stepRotation,
                StepMoveInertiaRatio = center.stepMoveInertiaRatio,
                StepRotationInertiaRatio = center.stepRotationInertiaRatio,
                InertiaVector = center.inertiaVector,
                InertiaRotation = center.inertiaRotation,
                AngularVelocity = center.angularVelocity,
                RotationAxis = center.rotationAxis,
                ScaleRatio = team.scaleRatio,
                GravityDot = team.gravityDot,
                GravityRatio = team.gravityRatio,
                VelocityWeight = team.velocityWeight,
                BlendWeight = team.blendWeight,
            };
        }

        private static CenterStaticDump RunCenterStaticOracle()
        {
            float3[] positions =
            {
                new float3(0, 0, 0), new float3(2, 0, 0),
                new float3(0, 2, 0), new float3(0, 0, 3),
            };
            using (var mesh = new VirtualMesh("center_static_fixed_001"))
            {
                int count = positions.Length;
                mesh.isBoneCloth = false;
                mesh.meshType = VirtualMesh.MeshType.NormalMesh;
                mesh.localPositions = new ExSimpleNativeArray<float3>(positions);
                mesh.localNormals = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(0, 0, 1), count).ToArray()
                );
                mesh.localTangents = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(1, 0, 0), count).ToArray()
                );
                mesh.uv = new ExSimpleNativeArray<float2>(
                    new[] { new float2(0, 0), new float2(1, 0), new float2(0, 1), new float2(0, 0) }
                );
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    new[]
                    {
                        new VertexAttribute(1), new VertexAttribute(2),
                        new VertexAttribute(1), new VertexAttribute(1),
                    }
                );
                mesh.referenceIndices = new ExSimpleNativeArray<int>(Enumerable.Range(0, count).ToArray());
                mesh.boneWeights = new ExSimpleNativeArray<VirtualMeshBoneWeight>(
                    Enumerable.Repeat(
                        new VirtualMeshBoneWeight(new int4(0), new float4(1, 0, 0, 0)), count
                    ).ToArray()
                );
                mesh.triangles = new ExSimpleNativeArray<int3>(new[] { new int3(0, 1, 2) });
                mesh.lines = new ExSimpleNativeArray<int2>(Array.Empty<int2>());
                mesh.initLocalToWorld = float4x4.identity;
                mesh.initWorldToLocal = float4x4.identity;
                mesh.initRotation = quaternion.identity;
                mesh.initInverseRotation = quaternion.identity;
                mesh.initScale = 1;
                mesh.boundingBox = new NativeReference<AABB>(Allocator.Persistent);

                var recordObject = new GameObject("center_static_fixed_001_record");
                try
                {
                    var record = new TransformRecord(recordObject.transform, true);
                    mesh.ConvertProxyMesh(new ClothSerializeData(), record, new List<TransformRecord>(), record);
                    if (mesh.result.IsError())
                    {
                        throw new InvalidOperationException($"Center proxy conversion failed: {mesh.result.Result}");
                    }
                    var parameters = new ClothParameters
                    {
                        worldGravityDirection = math.normalize(new float3(1.0f, -2.0f, 0.5f)),
                    };
                    InertiaConstraint.ConstraintData inertia = InertiaConstraint.CreateData(mesh, parameters);
                    return new CenterStaticDump
                    {
                        FixedIndices = (mesh.centerFixedList ?? Array.Empty<ushort>())
                            .Select(value => (int)value).ToArray(),
                        LocalCenterPosition = mesh.localCenterPosition.Value,
                        InitialLocalGravityDirection = inertia.initLocalGravityDirection,
                    };
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(recordObject);
                }
            }
        }

        private static int WriteFrameFixtures(string outputDirectory)
        {
            FrameResetDump dump = RunFrameResetOracle();
            string path = Path.Combine(outputDirectory, "frame_reset_pose_001.json");
            File.WriteAllText(path, BuildFrameResetJson(dump), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
            return 1;
        }

        private static FrameResetDump RunFrameResetOracle()
        {
            int count = 2;
            var positions = new NativeArray<float3>(count, Allocator.TempJob);
            var rotations = new NativeArray<quaternion>(count, Allocator.TempJob);
            var depths = new NativeArray<float>(count, Allocator.TempJob);
            var next = new NativeArray<float3>(count, Allocator.TempJob);
            var old = new NativeArray<float3>(count, Allocator.TempJob);
            var oldRot = new NativeArray<quaternion>(count, Allocator.TempJob);
            var basePos = new NativeArray<float3>(count, Allocator.TempJob);
            var baseRot = new NativeArray<quaternion>(count, Allocator.TempJob);
            var animationOld = new NativeArray<float3>(count, Allocator.TempJob);
            var animationOldRot = new NativeArray<quaternion>(count, Allocator.TempJob);
            var velocityReference = new NativeArray<float3>(count, Allocator.TempJob);
            var display = new NativeArray<float3>(count, Allocator.TempJob);
            var velocity = new NativeArray<float3>(count, Allocator.TempJob);
            var realVelocity = new NativeArray<float3>(count, Allocator.TempJob);
            var friction = new NativeArray<float>(count, Allocator.TempJob);
            var staticFriction = new NativeArray<float>(count, Allocator.TempJob);
            var collisionNormal = new NativeArray<float3>(count, Allocator.TempJob);
            try
            {
                positions[0] = new float3(1.25f, -2.0f, 3.5f);
                positions[1] = new float3(-4.0f, 5.5f, 0.75f);
                rotations[0] = MathUtility.ToRotation(new float3(0, 1, 0), new float3(0, 0, 1));
                float invSqrt2 = math.rsqrt(2.0f);
                rotations[1] = MathUtility.ToRotation(
                    new float3(invSqrt2, invSqrt2, 0),
                    new float3(0, 0, 1)
                );
                for (int index = 0; index < count; index++)
                {
                    float marker = 10.0f + index;
                    next[index] = marker;
                    old[index] = marker;
                    oldRot[index] = new quaternion(marker, marker, marker, marker);
                    basePos[index] = marker;
                    baseRot[index] = new quaternion(marker, marker, marker, marker);
                    animationOld[index] = marker;
                    animationOldRot[index] = new quaternion(marker, marker, marker, marker);
                    velocityReference[index] = marker;
                    display[index] = marker;
                    velocity[index] = marker;
                    realVelocity[index] = marker;
                    friction[index] = marker;
                    staticFriction[index] = marker;
                    collisionNormal[index] = marker;
                }

                var team = new TeamManager.TeamData
                {
                    particleChunk = new DataChunk(0, count),
                    proxyCommonChunk = new DataChunk(0, count),
                };
                team.flag.SetBits(TeamManager.Flag_Reset, true);
                MethodInfo method = typeof(SimulationManager).GetMethod(
                    "SimulationPreTeamUpdate",
                    BindingFlags.NonPublic | BindingFlags.Static
                );
                if (method == null)
                {
                    throw new MissingMethodException("SimulationPreTeamUpdate");
                }
                object[] arguments =
                {
                    new DataChunk(0, count), team, new ClothParameters(),
                    new InertiaConstraint.CenterData(), positions, rotations, depths,
                    next, old, oldRot, basePos, baseRot, animationOld, animationOldRot,
                    velocityReference, display, velocity, realVelocity, friction,
                    staticFriction, collisionNormal,
                };
                InvokeStatic(method, arguments);
                return new FrameResetDump
                {
                    WorldPositions = positions.ToArray(),
                    WorldRotations = rotations.ToArray(),
                    NextPositions = next.ToArray(),
                    OldPositions = old.ToArray(),
                    OldRotations = oldRot.ToArray(),
                    BasePositions = basePos.ToArray(),
                    BaseRotations = baseRot.ToArray(),
                    AnimationOldPositions = animationOld.ToArray(),
                    AnimationOldRotations = animationOldRot.ToArray(),
                    VelocityReferencePositions = velocityReference.ToArray(),
                    DisplayPositions = display.ToArray(),
                    Velocities = velocity.ToArray(),
                    RealVelocities = realVelocity.ToArray(),
                    Friction = friction.ToArray(),
                    StaticFriction = staticFriction.ToArray(),
                    CollisionNormals = collisionNormal.ToArray(),
                };
            }
            finally
            {
                positions.Dispose(); rotations.Dispose(); depths.Dispose();
                next.Dispose(); old.Dispose(); oldRot.Dispose(); basePos.Dispose(); baseRot.Dispose();
                animationOld.Dispose(); animationOldRot.Dispose(); velocityReference.Dispose();
                display.Dispose(); velocity.Dispose(); realVelocity.Dispose(); friction.Dispose();
                staticFriction.Dispose(); collisionNormal.Dispose();
            }
        }

        private static int WriteParameterFixtures(string outputDirectory)
        {
            var mesh = new ClothSerializeData();
            SetHostProfileCurveDefaults(mesh);
            mesh.clothType = ClothProcess.ClothType.MeshCloth;
            mesh.gravityDirection = new float3(0.0f, 0.0f, -1.0f);
            mesh.damping = new CurveSerializeData(
                0.5f,
                new AnimationCurve(
                    new Keyframe(0.0f, 0.0f, 0.0f, 0.0f),
                    new Keyframe(0.5f, 1.0f, 0.0f, 0.0f),
                    new Keyframe(1.0f, 0.25f, 0.0f, 0.0f)
                )
            );
            WriteParameterFixture(
                outputDirectory,
                "runtime_parameters_mesh_curve_001",
                "MeshCloth curve sampling at i/15 plus ordinary conversion rules.",
                PackRuntimeParameters(mesh.GetClothParameters())
            );

            var spring = new ClothSerializeData();
            SetHostProfileCurveDefaults(spring);
            spring.clothType = ClothProcess.ClothType.BoneSpring;
            spring.gravity = 9.0f;
            spring.tetherConstraint.distanceCompression = 0.25f;
            spring.distanceConstraint.stiffness.SetValue(0.9f);
            spring.motionConstraint.useMaxDistance = true;
            spring.motionConstraint.useBackstop = true;
            spring.colliderCollisionConstraint.mode = ColliderCollisionConstraint.Mode.Edge;
            spring.colliderCollisionConstraint.friction = 0.1f;
            spring.colliderCollisionConstraint.limitDistance.SetValue(0.125f);
            spring.selfCollisionConstraint.selfMode = SelfCollisionConstraint.SelfCollisionMode.FullMesh;
            spring.selfCollisionConstraint.syncMode = SelfCollisionConstraint.SelfCollisionMode.FullMesh;
            spring.springConstraint.useSpring = true;
            spring.springConstraint.springPower = 0.3f;
            WriteParameterFixture(
                outputDirectory,
                "runtime_parameters_bone_spring_001",
                "BoneSpring fixed overrides from GetClothParameters().",
                PackRuntimeParameters(spring.GetClothParameters())
            );
            return 2;
        }

        private static void SetHostProfileCurveDefaults(ClothSerializeData value)
        {
            value.damping.SetValue(0.05f);
            value.radius.SetValue(0.02f);
            value.distanceConstraint.stiffness.SetValue(1.0f);
            value.angleRestorationConstraint.stiffness.SetValue(0.2f);
            value.angleLimitConstraint.limitAngle.SetValue(60.0f);
            value.motionConstraint.maxDistance.SetValue(0.3f);
            value.motionConstraint.backstopDistance.SetValue(0.0f);
            value.colliderCollisionConstraint.limitDistance.SetValue(0.05f);
            value.selfCollisionConstraint.surfaceThickness.SetValue(0.005f);
        }

        private static void WriteParameterFixture(
            string outputDirectory,
            string caseId,
            string note,
            ParameterRuntimeDump expected
        )
        {
            var output = new ParameterOracleOutput
            {
                case_id = caseId,
                note = note,
                expected = expected,
            };
            string path = Path.Combine(outputDirectory, caseId + ".json");
            File.WriteAllText(path, JsonUtility.ToJson(output, true), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
        }

        private static ParameterRuntimeDump PackRuntimeParameters(ClothParameters value)
        {
            var inertia = value.inertiaConstraint;
            var tether = value.tetherConstraint;
            var distance = value.distanceConstraint;
            var bending = value.triangleBendingConstraint;
            var angle = value.angleConstraint;
            var motion = value.motionConstraint;
            var collision = value.colliderCollisionConstraint;
            var selfCollision = value.selfCollisionConstraint;
            var wind = value.wind;
            var spring = value.springConstraint;
            return new ParameterRuntimeDump
            {
                float_values = new[]
                {
                    value.gravity,
                    value.worldGravityDirection.x, value.worldGravityDirection.y, value.worldGravityDirection.z,
                    value.gravityFalloff, value.stablizationTimeAfterReset, value.blendWeight,
                    value.rotationalInterpolation, value.rootRotation,
                    value.culling.distanceCullingLength, value.culling.distanceCullingFadeRatio,
                    inertia.anchorInertia, inertia.worldInertia, inertia.movementInertiaSmoothing,
                    inertia.movementSpeedLimit, inertia.rotationSpeedLimit, inertia.localInertia,
                    inertia.localMovementSpeedLimit, inertia.localRotationSpeedLimit, inertia.depthInertia,
                    inertia.centrifualAcceleration, inertia.particleSpeedLimit,
                    inertia.teleportDistance, inertia.teleportRotation,
                    tether.compressionLimit, tether.stretchLimit,
                    distance.velocityAttenuation, bending.stiffness,
                    angle.restorationVelocityAttenuation, angle.restorationGravityFalloff,
                    angle.limitstiffness, motion.backstopRadius, motion.stiffness,
                    collision.dynamicFriction, collision.staticFriction, selfCollision.clothMass,
                    wind.influence, wind.frequency, wind.turbulence, wind.blend,
                    wind.synchronization, wind.depthWeight, wind.movingWind,
                    spring.springPower, spring.limitDistance, spring.normalLimitRatio, spring.springNoise,
                },
                int_values = new[]
                {
                    (int)value.normalAxis,
                    value.culling.useDistanceCulling ? 1 : 0,
                    (int)inertia.teleportMode,
                    (int)bending.method,
                    angle.useAngleRestoration ? 1 : 0,
                    angle.useAngleLimit ? 1 : 0,
                    motion.useMaxDistance ? 1 : 0,
                    motion.useBackstop ? 1 : 0,
                    (int)collision.mode,
                    (int)selfCollision.selfMode,
                    (int)selfCollision.syncMode,
                },
                curve_values = new[]
                {
                    value.dampingCurveData,
                    value.radiusCurveData,
                    distance.restorationStiffness,
                    angle.restorationStiffness,
                    angle.limitCurveData,
                    motion.maxDistanceCurveData,
                    motion.backstopDistanceCurveData,
                    collision.limitDistance,
                    selfCollision.surfaceThicknessCurveData,
                }.SelectMany(MatrixValues).ToArray(),
            };
        }

        private static IEnumerable<float> MatrixValues(float4x4 value)
        {
            yield return value.c0.x; yield return value.c0.y; yield return value.c0.z; yield return value.c0.w;
            yield return value.c1.x; yield return value.c1.y; yield return value.c1.z; yield return value.c1.w;
            yield return value.c2.x; yield return value.c2.y; yield return value.c2.z; yield return value.c2.w;
            yield return value.c3.x; yield return value.c3.y; yield return value.c3.z; yield return value.c3.w;
        }

        private static OracleDump RunCase(OracleCase oracleCase)
        {
            using (var mesh = new VirtualMesh(oracleCase.Id))
            {
                int count = oracleCase.Positions.Length;
                mesh.isBoneCloth = false;
                mesh.localPositions = new ExSimpleNativeArray<float3>(oracleCase.Positions);
                mesh.localNormals = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(0.0f, 0.0f, 1.0f), count).ToArray()
                );
                mesh.localTangents = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(1.0f, 0.0f, 0.0f), count).ToArray()
                );
                mesh.uv = new ExSimpleNativeArray<float2>(new float2[count]);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    oracleCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );

                BuildAdjacency(oracleCase.Adjacency, out uint[] indexArray, out ushort[] dataArray);
                mesh.vertexToVertexIndexArray = new NativeArray<uint>(indexArray, Allocator.Persistent);
                mesh.vertexToVertexDataArray = new NativeArray<ushort>(dataArray, Allocator.Persistent);

                InvokePrivate(mesh, "CreateMeshBaseLine");
                InvokePrivate(mesh, "CreateBaseLinePose");
                InvokePrivate(mesh, "CreateVertexRootAndDepth");

                return ReadDump(mesh);
            }
        }

        private static ProxyDump RunProxyCase(ProxyCase proxyCase)
        {
            using (var mesh = new VirtualMesh(proxyCase.Id))
            {
                int count = proxyCase.Positions.Length;
                mesh.isBoneCloth = false;
                mesh.meshType = VirtualMesh.MeshType.NormalMesh;
                mesh.localPositions = new ExSimpleNativeArray<float3>(proxyCase.Positions);
                mesh.localNormals = new ExSimpleNativeArray<float3>(proxyCase.Normals);
                mesh.localTangents = new ExSimpleNativeArray<float3>(proxyCase.Tangents);
                mesh.uv = new ExSimpleNativeArray<float2>(proxyCase.Uvs);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    proxyCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.referenceIndices = new ExSimpleNativeArray<int>(
                    Enumerable.Range(0, count).ToArray()
                );
                mesh.boneWeights = new ExSimpleNativeArray<VirtualMeshBoneWeight>(
                    Enumerable
                        .Repeat(
                            new VirtualMeshBoneWeight(
                                new int4(0, 0, 0, 0),
                                new float4(1.0f, 0.0f, 0.0f, 0.0f)
                            ),
                            count
                        )
                        .ToArray()
                );
                mesh.triangles = new ExSimpleNativeArray<int3>(proxyCase.Triangles);
                mesh.lines = new ExSimpleNativeArray<int2>(proxyCase.Lines);
                mesh.initLocalToWorld = float4x4.identity;
                mesh.initWorldToLocal = float4x4.identity;
                mesh.initRotation = quaternion.identity;
                mesh.initInverseRotation = quaternion.identity;
                mesh.initScale = new float3(1.0f, 1.0f, 1.0f);
                mesh.boundingBox = new NativeReference<AABB>(Allocator.Persistent);

                var sdata = new ClothSerializeData();
                var recordObject = new GameObject(proxyCase.Id + "_record");
                try
                {
                    var record = new TransformRecord(recordObject.transform, true);
                    mesh.ConvertProxyMesh(
                        sdata,
                        record,
                        new List<TransformRecord>(),
                        record
                    );
                    if (mesh.result.IsError())
                    {
                        throw new InvalidOperationException(
                            $"ConvertProxyMesh failed for {proxyCase.Id}: {mesh.result.Result}"
                        );
                    }
                    return ReadProxyDump(mesh);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(recordObject);
                }
            }
        }

        private static DistanceDump RunDistanceCase(DistanceCase distanceCase)
        {
            using (var mesh = new VirtualMesh(distanceCase.Id))
            {
                mesh.isBoneCloth = false;
                mesh.localPositions = new ExSimpleNativeArray<float3>(distanceCase.Positions);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    distanceCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.vertexParentIndices = new NativeArray<int>(
                    distanceCase.Parents,
                    Allocator.Persistent
                );
                mesh.edges = new NativeArray<int2>(distanceCase.Edges, Allocator.Persistent);
                mesh.triangles = new ExSimpleNativeArray<int3>(distanceCase.Triangles);

                BuildAdjacency(
                    distanceCase.Adjacency,
                    out uint[] vertexToVertexIndices,
                    out ushort[] vertexToVertexData
                );
                mesh.vertexToVertexIndexArray = new NativeArray<uint>(
                    vertexToVertexIndices,
                    Allocator.Persistent
                );
                mesh.vertexToVertexDataArray = new NativeArray<ushort>(
                    vertexToVertexData,
                    Allocator.Persistent
                );
                mesh.edgeToTriangles = BuildEdgeToTriangles(distanceCase.Triangles);

                DistanceConstraint.ConstraintData data = DistanceConstraint.CreateData(
                    mesh,
                    new ClothParameters()
                );
                uint[] packed = data.indexArray ?? Array.Empty<uint>();
                var ranges = new int2[packed.Length];
                for (int index = 0; index < packed.Length; index++)
                {
                    DataUtility.Unpack12_20(packed[index], out int count, out int start);
                    ranges[index] = new int2(start, count);
                }
                return new DistanceDump
                {
                    PackedIndices = packed,
                    Ranges = ranges,
                    Targets = (data.dataArray ?? Array.Empty<ushort>())
                        .Select(value => (int)value)
                        .ToArray(),
                    RestSigned = data.distanceArray ?? Array.Empty<float>(),
                };
            }
        }

        private static NativeParallelMultiHashMap<int2, ushort> BuildEdgeToTriangles(
            int3[] triangles
        )
        {
            var map = new NativeParallelMultiHashMap<int2, ushort>(
                Math.Max(1, triangles.Length * 3),
                Allocator.Persistent
            );
            for (int triangleIndex = 0; triangleIndex < triangles.Length; triangleIndex++)
            {
                int3 triangle = triangles[triangleIndex];
                foreach (int2 edge in new[]
                {
                    SortedEdge(triangle.x, triangle.y),
                    SortedEdge(triangle.y, triangle.z),
                    SortedEdge(triangle.z, triangle.x),
                })
                {
                    map.Add(edge, checked((ushort)triangleIndex));
                }
            }
            return map;
        }

        private static int2 SortedEdge(int x, int y)
        {
            return x <= y ? new int2(x, y) : new int2(y, x);
        }

        private static DistanceRuntimeDump RunDistanceRuntimeCase(
            DistanceRuntimeCase runtimeCase
        )
        {
            MethodInfo method = typeof(DistanceConstraint).GetMethod(
                "SolverConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(DistanceConstraint).FullName,
                    "SolverConstraint"
                );
            }

            var team = new TeamManager.TeamData
            {
                initScale = new float3(1.0f),
                scaleRatio = 1.0f,
                animationPoseRatio = 0.0f,
                proxyCommonChunk = new DataChunk(0, 3),
                particleChunk = new DataChunk(0, 3),
                distanceStartChunk = new DataChunk(0, 3),
                distanceDataChunk = new DataChunk(0, runtimeCase.Targets.Length),
            };
            var parameters = new ClothParameters();
            parameters.distanceConstraint.Convert(
                new DistanceConstraint.SerializeData(),
                ClothProcess.ClothType.MeshCloth
            );

            var attributes = new NativeArray<VertexAttribute>(
                new[]
                {
                    VertexAttribute.Move,
                    VertexAttribute.Fixed,
                    VertexAttribute.Fixed,
                },
                Allocator.Persistent
            );
            var depths = new NativeArray<float>(
                new[] { 0.5f, 0.0f, 0.0f },
                Allocator.Persistent
            );
            var nextPositions = new NativeArray<float3>(
                P((0, 0, 0), (2, 0, 0), (4, 0, 0)),
                Allocator.Persistent
            );
            var basePositions = new NativeArray<float3>(
                P((0, 0, 0), (1, 0, 0), (0, 0, 0)),
                Allocator.Persistent
            );
            var velocityPositions = new NativeArray<float3>(
                new float3[3],
                Allocator.Persistent
            );
            var friction = new NativeArray<float>(new float[3], Allocator.Persistent);
            var indices = new NativeArray<uint>(
                new[]
                {
                    DataUtility.Pack12_20(runtimeCase.Targets.Length, 0),
                    DataUtility.Pack12_20(0, runtimeCase.Targets.Length),
                    DataUtility.Pack12_20(0, runtimeCase.Targets.Length),
                },
                Allocator.Persistent
            );
            var targets = new NativeArray<ushort>(
                runtimeCase.Targets.Select(value => checked((ushort)value)).ToArray(),
                Allocator.Persistent
            );
            var rests = new NativeArray<float>(runtimeCase.RestSigned, Allocator.Persistent);
            try
            {
                object[] arguments =
                {
                    new DataChunk(0, 3),
                    new float4(0.0f, 1.0f, 0.0f, 0.0f),
                    team,
                    parameters,
                    attributes,
                    depths,
                    nextPositions,
                    basePositions,
                    velocityPositions,
                    friction,
                    indices,
                    targets,
                    rests,
                };
                try
                {
                    method.Invoke(null, arguments);
                }
                catch (TargetInvocationException exception) when (exception.InnerException != null)
                {
                    ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                    throw;
                }
                return new DistanceRuntimeDump
                {
                    NextPositions = nextPositions.ToArray(),
                    VelocityPositions = velocityPositions.ToArray(),
                };
            }
            finally
            {
                attributes.Dispose();
                depths.Dispose();
                nextPositions.Dispose();
                basePositions.Dispose();
                velocityPositions.Dispose();
                friction.Dispose();
                indices.Dispose();
                targets.Dispose();
                rests.Dispose();
            }
        }

        private static ParticleStepDump RunParticleStepOracle()
        {
            MethodInfo method = typeof(SimulationManager).GetMethod(
                "SimulationStepUpdateParticles",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(SimulationManager).FullName,
                    "SimulationStepUpdateParticles"
                );
            }

            var team = new TeamManager.TeamData
            {
                proxyCommonChunk = new DataChunk(0, 2),
                particleChunk = new DataChunk(0, 2),
                frameInterpolation = 1.0f,
                gravityRatio = 0.75f,
                initScale = new float3(1.0f),
                scaleRatio = 1.5f,
                velocityWeight = 0.8f,
                forceMode = ClothForceMode.None,
            };
            var center = new InertiaConstraint.CenterData
            {
                oldWorldPosition = float3.zero,
                stepVector = float3.zero,
                stepRotation = quaternion.identity,
                inertiaVector = float3.zero,
                inertiaRotation = quaternion.identity,
            };
            var parameters = new ClothParameters
            {
                gravity = 9.0f,
                worldGravityDirection = new float3(0.0f, -1.0f, 0.0f),
                dampingCurveData = new float4x4(
                    new float4(0.2f), new float4(0.2f),
                    new float4(0.2f), new float4(0.2f)
                ),
            };
            var teamWind = new TeamWindData();
            var windData = new NativeArray<WindManager.WindData>(0, Allocator.Persistent);
            var attributes = new NativeArray<VertexAttribute>(
                new[] { VertexAttribute.Move, VertexAttribute.Fixed },
                Allocator.Persistent
            );
            var depths = new NativeArray<float>(new[] { 0.5f, 0.0f }, Allocator.Persistent);
            var positions = new NativeArray<float3>(
                P((0, 0, 0), (10, 0, 0)), Allocator.Persistent
            );
            var rotations = new NativeArray<quaternion>(
                new[] { quaternion.identity, quaternion.identity }, Allocator.Persistent
            );
            var roots = new NativeArray<int>(new[] { 0, 0 }, Allocator.Persistent);
            var next = new NativeArray<float3>(2, Allocator.Persistent);
            var old = new NativeArray<float3>(
                P((1, 2, 3), (4, 5, 6)), Allocator.Persistent
            );
            var basePositions = new NativeArray<float3>(2, Allocator.Persistent);
            var baseRotations = new NativeArray<quaternion>(2, Allocator.Persistent);
            var oldAnimatedPositions = new NativeArray<float3>(
                P((-1, -1, -1), (-2, -2, -2)), Allocator.Persistent
            );
            var oldAnimatedRotations = new NativeArray<quaternion>(
                new[] { quaternion.identity, quaternion.identity }, Allocator.Persistent
            );
            var velocityPositions = new NativeArray<float3>(2, Allocator.Persistent);
            var velocities = new NativeArray<float3>(
                P((2, -1, 0.5f), (9, 9, 9)), Allocator.Persistent
            );
            var friction = new NativeArray<float>(new float[2], Allocator.Persistent);
            var stepBasicPositions = new NativeArray<float3>(2, Allocator.Persistent);
            var stepBasicRotations = new NativeArray<quaternion>(2, Allocator.Persistent);
            var tempVectorA = new NativeArray<float3>(
                P((7, 7, 7), (7, 7, 7)), Allocator.Persistent
            );
            var tempVectorB = new NativeArray<float3>(
                P((8, 8, 8), (8, 8, 8)), Allocator.Persistent
            );
            var tempCounts = new NativeArray<int>(new[] { 7, 8 }, Allocator.Persistent);
            var tempFloats = new NativeArray<float>(new[] { 7.0f, 8.0f }, Allocator.Persistent);
            try
            {
                object[] arguments =
                {
                    new DataChunk(0, 2),
                    new float4(1.0f, 1.0f, 0.5f, 1.0f),
                    0.1f,
                    0,
                    team,
                    center,
                    parameters,
                    teamWind,
                    windData,
                    attributes,
                    depths,
                    positions,
                    rotations,
                    roots,
                    next,
                    old,
                    basePositions,
                    baseRotations,
                    oldAnimatedPositions,
                    oldAnimatedRotations,
                    velocityPositions,
                    velocities,
                    friction,
                    stepBasicPositions,
                    stepBasicRotations,
                    tempVectorA,
                    tempVectorB,
                    tempCounts,
                    tempFloats,
                };
                try
                {
                    method.Invoke(null, arguments);
                }
                catch (TargetInvocationException exception) when (exception.InnerException != null)
                {
                    ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                    throw;
                }
                return new ParticleStepDump
                {
                    BasePositions = basePositions.ToArray(),
                    NextPositions = next.ToArray(),
                    VelocityPositions = velocityPositions.ToArray(),
                    TempVectorA = tempVectorA.ToArray(),
                    TempVectorB = tempVectorB.ToArray(),
                    TempCounts = tempCounts.ToArray(),
                    TempFloats = tempFloats.ToArray(),
                };
            }
            finally
            {
                windData.Dispose(); attributes.Dispose(); depths.Dispose(); positions.Dispose();
                rotations.Dispose(); roots.Dispose(); next.Dispose(); old.Dispose();
                basePositions.Dispose(); baseRotations.Dispose(); oldAnimatedPositions.Dispose();
                oldAnimatedRotations.Dispose(); velocityPositions.Dispose(); velocities.Dispose();
                friction.Dispose(); stepBasicPositions.Dispose(); stepBasicRotations.Dispose();
                tempVectorA.Dispose(); tempVectorB.Dispose(); tempCounts.Dispose(); tempFloats.Dispose();
            }
        }

        private static ParticleInertiaStepDump RunParticleInertiaStepOracle()
        {
            MethodInfo method = typeof(SimulationManager).GetMethod(
                "SimulationStepUpdateParticles",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(SimulationManager).FullName,
                    "SimulationStepUpdateParticles"
                );
            }

            quaternion stepRotation = quaternion.AxisAngle(math.forward(), math.radians(90.0f));
            quaternion inertiaRotation = quaternion.AxisAngle(math.forward(), math.radians(30.0f));
            var team = new TeamManager.TeamData
            {
                proxyCommonChunk = new DataChunk(0, 1),
                particleChunk = new DataChunk(0, 1),
                frameInterpolation = 1.0f,
                gravityRatio = 1.0f,
                initScale = new float3(1.0f),
                scaleRatio = 1.0f,
                velocityWeight = 0.75f,
                forceMode = ClothForceMode.None,
            };
            var center = new InertiaConstraint.CenterData
            {
                oldWorldPosition = new float3(1.0f, 1.0f, 1.0f),
                stepVector = new float3(2.0f, 0.0f, 0.0f),
                stepRotation = stepRotation,
                inertiaVector = new float3(0.5f, 0.0f, 0.0f),
                inertiaRotation = inertiaRotation,
            };
            var parameters = new ClothParameters
            {
                gravity = 0.0f,
                worldGravityDirection = new float3(0.0f, -1.0f, 0.0f),
                dampingCurveData = new float4x4(0.0f),
                inertiaConstraint = new InertiaConstraint.InertiaConstraintParams
                {
                    depthInertia = 0.8f,
                },
            };
            var teamWind = new TeamWindData();
            var windData = new NativeArray<WindManager.WindData>(0, Allocator.Persistent);
            var attributes = new NativeArray<VertexAttribute>(
                new[] { VertexAttribute.Move }, Allocator.Persistent
            );
            var depths = new NativeArray<float>(new[] { 0.5f }, Allocator.Persistent);
            var positions = new NativeArray<float3>(P((9, 9, 9)), Allocator.Persistent);
            var rotations = new NativeArray<quaternion>(
                new[] { quaternion.identity }, Allocator.Persistent
            );
            var roots = new NativeArray<int>(new[] { 0 }, Allocator.Persistent);
            var next = new NativeArray<float3>(1, Allocator.Persistent);
            var old = new NativeArray<float3>(P((3, 2, 1)), Allocator.Persistent);
            var basePositions = new NativeArray<float3>(1, Allocator.Persistent);
            var baseRotations = new NativeArray<quaternion>(1, Allocator.Persistent);
            var oldAnimatedPositions = new NativeArray<float3>(P((8, 8, 8)), Allocator.Persistent);
            var oldAnimatedRotations = new NativeArray<quaternion>(
                new[] { quaternion.identity }, Allocator.Persistent
            );
            var velocityPositions = new NativeArray<float3>(1, Allocator.Persistent);
            var velocities = new NativeArray<float3>(P((1, 0, 0)), Allocator.Persistent);
            var friction = new NativeArray<float>(1, Allocator.Persistent);
            var stepBasicPositions = new NativeArray<float3>(1, Allocator.Persistent);
            var stepBasicRotations = new NativeArray<quaternion>(1, Allocator.Persistent);
            var tempVectorA = new NativeArray<float3>(1, Allocator.Persistent);
            var tempVectorB = new NativeArray<float3>(1, Allocator.Persistent);
            var tempCounts = new NativeArray<int>(1, Allocator.Persistent);
            var tempFloats = new NativeArray<float>(1, Allocator.Persistent);
            try
            {
                object[] arguments =
                {
                    new DataChunk(0, 1),
                    new float4(1.0f, 1.0f, 0.0f, 1.0f),
                    0.1f,
                    0,
                    team,
                    center,
                    parameters,
                    teamWind,
                    windData,
                    attributes,
                    depths,
                    positions,
                    rotations,
                    roots,
                    next,
                    old,
                    basePositions,
                    baseRotations,
                    oldAnimatedPositions,
                    oldAnimatedRotations,
                    velocityPositions,
                    velocities,
                    friction,
                    stepBasicPositions,
                    stepBasicRotations,
                    tempVectorA,
                    tempVectorB,
                    tempCounts,
                    tempFloats,
                };
                try
                {
                    method.Invoke(null, arguments);
                }
                catch (TargetInvocationException exception) when (exception.InnerException != null)
                {
                    ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                    throw;
                }
                return new ParticleInertiaStepDump
                {
                    BasePositions = basePositions.ToArray(),
                    BaseRotations = baseRotations.ToArray(),
                    StepBasicPositions = stepBasicPositions.ToArray(),
                    StepBasicRotations = stepBasicRotations.ToArray(),
                    NextPositions = next.ToArray(),
                    VelocityPositions = velocityPositions.ToArray(),
                };
            }
            finally
            {
                windData.Dispose(); attributes.Dispose(); depths.Dispose(); positions.Dispose();
                rotations.Dispose(); roots.Dispose(); next.Dispose(); old.Dispose();
                basePositions.Dispose(); baseRotations.Dispose(); oldAnimatedPositions.Dispose();
                oldAnimatedRotations.Dispose(); velocityPositions.Dispose(); velocities.Dispose();
                friction.Dispose(); stepBasicPositions.Dispose(); stepBasicRotations.Dispose();
                tempVectorA.Dispose(); tempVectorB.Dispose(); tempCounts.Dispose(); tempFloats.Dispose();
            }
        }

        private static BendingDump RunBendingCase(BendingCase bendingCase)
        {
            using (var mesh = new VirtualMesh(bendingCase.Id))
            {
                mesh.localPositions = new ExSimpleNativeArray<float3>(bendingCase.Positions);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    bendingCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.edges = new NativeArray<int2>(bendingCase.Edges, Allocator.Persistent);
                mesh.triangles = new ExSimpleNativeArray<int3>(bendingCase.Triangles);
                mesh.edgeToTriangles = BuildEdgeToTriangles(bendingCase.Triangles);
                mesh.initLocalToWorld = bendingCase.InitLocalToWorld;

                TriangleBendingConstraint.ConstraintData data =
                    TriangleBendingConstraint.CreateData(mesh, new ClothParameters());
                if (data == null)
                {
                    return new BendingDump
                    {
                        CreateReturnedNull = true,
                        RawPackedQuads = Array.Empty<ulong>(),
                        OrderedQuads = Array.Empty<int4>(),
                        RestAngleOrVolume = Array.Empty<float>(),
                        SignOrVolume = Array.Empty<int>(),
                        RawWriteData = Array.Empty<uint>(),
                        RawWriteIndices = Array.Empty<uint>(),
                        WriteRanges = Array.Empty<int2>(),
                    };
                }
                ulong[] packed = data.trianglePairArray ?? Array.Empty<ulong>();
                uint[] writeIndices = data.writeIndexArray ?? Array.Empty<uint>();
                var writeRanges = new int2[writeIndices.Length];
                for (int index = 0; index < writeIndices.Length; index++)
                {
                    DataUtility.Unpack12_20(writeIndices[index], out int count, out int start);
                    writeRanges[index] = new int2(start, count);
                }
                return new BendingDump
                {
                    CreateReturnedNull = false,
                    RawPackedQuads = packed,
                    OrderedQuads = packed.Select(value => DataUtility.Unpack64(value)).ToArray(),
                    RestAngleOrVolume = data.restAngleOrVolumeArray ?? Array.Empty<float>(),
                    SignOrVolume = (data.signOrVolumeArray ?? Array.Empty<sbyte>())
                        .Select(value => (int)value)
                        .ToArray(),
                    WriteBufferCount = data.writeBufferCount,
                    RawWriteData = data.writeDataArray ?? Array.Empty<uint>(),
                    RawWriteIndices = writeIndices,
                    WriteRanges = writeRanges,
                };
            }
        }

        private static BendingRuntimeDump RunBendingRuntimeCase(
            BendingRuntimeCase runtimeCase
        )
        {
            MethodInfo solver = typeof(TriangleBendingConstraint).GetMethod(
                "SolverConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            MethodInfo sum = typeof(TriangleBendingConstraint).GetMethod(
                "SumConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (solver == null || sum == null)
            {
                throw new MissingMethodException(
                    typeof(TriangleBendingConstraint).FullName,
                    solver == null ? "SolverConstraint" : "SumConstraint"
                );
            }
            int vertexCount = runtimeCase.NextPositions.Length;
            int recordCount = runtimeCase.OrderedQuads.Length;
            if (
                runtimeCase.Attributes.Length != vertexCount
                || runtimeCase.RestAngleOrVolume.Length != recordCount
                || runtimeCase.SignOrVolume.Length != recordCount
            )
            {
                throw new InvalidDataException($"Invalid bending runtime case shape: {runtimeCase.Id}");
            }
            var team = new TeamManager.TeamData
            {
                scaleRatio = runtimeCase.ScaleRatio,
                negativeScaleSign = runtimeCase.NegativeScaleSign,
                proxyCommonChunk = new DataChunk(0, vertexCount),
                particleChunk = new DataChunk(0, vertexCount),
                bendingPairChunk = new DataChunk(0, recordCount),
            };
            var parameters = new ClothParameters();
            parameters.triangleBendingConstraint.Convert(
                new TriangleBendingConstraint.SerializeData { stiffness = 1.0f }
            );
            var attributes = new NativeArray<VertexAttribute>(
                runtimeCase.Attributes.Select(value => new VertexAttribute(value)).ToArray(),
                Allocator.Persistent
            );
            var depths = new NativeArray<float>(
                Enumerable.Repeat(0.5f, vertexCount).ToArray(),
                Allocator.Persistent
            );
            var nextPositions = new NativeArray<float3>(
                runtimeCase.NextPositions,
                Allocator.Persistent
            );
            var friction = new NativeArray<float>(
                new float[vertexCount],
                Allocator.Persistent
            );
            var quads = new NativeArray<ulong>(
                runtimeCase.OrderedQuads.Select(value => DataUtility.Pack64(value)).ToArray(),
                Allocator.Persistent
            );
            var rests = new NativeArray<float>(
                runtimeCase.RestAngleOrVolume,
                Allocator.Persistent
            );
            var markers = new NativeArray<sbyte>(
                runtimeCase.SignOrVolume,
                Allocator.Persistent
            );
            var vectors = new NativeArray<float3>(vertexCount, Allocator.Persistent);
            var counts = new NativeArray<int>(vertexCount, Allocator.Persistent);
            try
            {
                InvokeStatic(
                    solver,
                    new object[]
                    {
                        new DataChunk(0, recordCount),
                        new float4(0.0f, 1.0f, 0.0f, 0.0f),
                        team,
                        parameters,
                        attributes,
                        depths,
                        nextPositions,
                        friction,
                        quads,
                        rests,
                        markers,
                        vectors,
                        counts,
                    }
                );
                int[] countBefore = counts.ToArray();
                int[] vectorBefore = vectors
                    .Reinterpret<int>(UnsafeUtility.SizeOf<float3>())
                    .ToArray();
                InvokeStatic(
                    sum,
                    new object[]
                    {
                        new DataChunk(0, vertexCount),
                        team,
                        parameters,
                        attributes,
                        nextPositions,
                        vectors,
                        counts,
                    }
                );
                return new BendingRuntimeDump
                {
                    CountBeforeSum = countBefore,
                    VectorComponentsBeforeSum = vectorBefore,
                    NextPositionsAfterSum = nextPositions.ToArray(),
                    CountAfterSum = counts.ToArray(),
                    VectorAfterSum = vectors.ToArray(),
                };
            }
            finally
            {
                attributes.Dispose();
                depths.Dispose();
                nextPositions.Dispose();
                friction.Dispose();
                quads.Dispose();
                rests.Dispose();
                markers.Dispose();
                vectors.Dispose();
                counts.Dispose();
            }
        }

        private static void InvokeStatic(MethodInfo method, object[] arguments)
        {
            try
            {
                method.Invoke(null, arguments);
            }
            catch (TargetInvocationException exception) when (exception.InnerException != null)
            {
                ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                throw;
            }
        }

        private static void BuildAdjacency(
            int[][] adjacency,
            out uint[] indexArray,
            out ushort[] dataArray
        )
        {
            indexArray = new uint[adjacency.Length];
            var data = new List<ushort>();
            for (int vertex = 0; vertex < adjacency.Length; vertex++)
            {
                int start = data.Count;
                foreach (int target in adjacency[vertex])
                {
                    data.Add(checked((ushort)target));
                }
                indexArray[vertex] = DataUtility.Pack12_20(adjacency[vertex].Length, start);
            }
            dataArray = data.ToArray();
        }

        private static void InvokePrivate(VirtualMesh mesh, string methodName)
        {
            MethodInfo method = typeof(VirtualMesh).GetMethod(
                methodName,
                BindingFlags.Instance | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(typeof(VirtualMesh).FullName, methodName);
            }

            try
            {
                method.Invoke(mesh, null);
            }
            catch (TargetInvocationException exception) when (exception.InnerException != null)
            {
                ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                throw;
            }
        }

        private static OracleDump ReadDump(VirtualMesh mesh)
        {
            VertexAttribute[] attributes = mesh.attributes.ToArray();
            uint[] childIndices = NativeArrayOrEmpty(mesh.vertexChildIndexArray);
            ushort[] childData = NativeArrayOrEmpty(mesh.vertexChildDataArray);
            ushort[] baselineStarts = NativeArrayOrEmpty(mesh.baseLineStartDataIndices);
            ushort[] baselineCounts = NativeArrayOrEmpty(mesh.baseLineDataCounts);
            ExBitFlag8[] baselineFlags = NativeArrayOrEmpty(mesh.baseLineFlags);
            quaternion[] localRotations = NativeArrayOrEmpty(mesh.vertexLocalRotations);

            var childRanges = new int2[childIndices.Length];
            for (int index = 0; index < childIndices.Length; index++)
            {
                DataUtility.Unpack12_20(childIndices[index], out int count, out int start);
                childRanges[index] = new int2(start, count);
            }

            int baselineRangeCount = Math.Min(baselineStarts.Length, baselineCounts.Length);
            var baselineRanges = new int2[baselineRangeCount];
            for (int index = 0; index < baselineRangeCount; index++)
            {
                baselineRanges[index] = new int2(baselineStarts[index], baselineCounts[index]);
            }

            return new OracleDump
            {
                FinalAttributes = attributes.Select(value => value.Value).ToArray(),
                Parents = NativeArrayOrEmpty(mesh.vertexParentIndices),
                ChildRanges = childRanges,
                ChildData = childData.Select(value => (int)value).ToArray(),
                BaselineFlags = baselineFlags.Select(value => value.Value).ToArray(),
                BaselineRanges = baselineRanges,
                BaselineData = NativeArrayOrEmpty(mesh.baseLineData).Select(value => (int)value).ToArray(),
                Roots = NativeArrayOrEmpty(mesh.vertexRootIndices),
                Depths = NativeArrayOrEmpty(mesh.vertexDepths),
                LocalPositions = NativeArrayOrEmpty(mesh.vertexLocalPositions),
                LocalRotations = localRotations.Select(value => value.value).ToArray(),
            };
        }

        private static ProxyDump ReadProxyDump(VirtualMesh mesh)
        {
            uint[] vertexToVertexIndices = NativeArrayOrEmpty(mesh.vertexToVertexIndexArray);
            ushort[] vertexToVertexData = NativeArrayOrEmpty(mesh.vertexToVertexDataArray);
            var vertexToVertexRanges = new int2[vertexToVertexIndices.Length];
            for (int index = 0; index < vertexToVertexIndices.Length; index++)
            {
                DataUtility.Unpack12_20(vertexToVertexIndices[index], out int count, out int start);
                vertexToVertexRanges[index] = new int2(start, count);
            }

            FixedList32Bytes<uint>[] rawVertexToTriangles =
                NativeArrayOrEmpty(mesh.vertexToTriangles);
            var vertexToTriangleRecords = new int2[rawVertexToTriangles.Length][];
            for (int vertex = 0; vertex < rawVertexToTriangles.Length; vertex++)
            {
                FixedList32Bytes<uint> records = rawVertexToTriangles[vertex];
                var decoded = new int2[records.Length];
                for (int index = 0; index < records.Length; index++)
                {
                    uint packed = records[index];
                    decoded[index] = new int2(
                        DataUtility.Unpack12_20Hi(packed),
                        DataUtility.Unpack12_20Low(packed)
                    );
                }
                vertexToTriangleRecords[vertex] = decoded;
            }

            quaternion[] bindPoseRotations = NativeArrayOrEmpty(mesh.vertexBindPoseRotations);
            return new ProxyDump
            {
                FinalAttributes = mesh.attributes.ToArray().Select(value => value.Value).ToArray(),
                Triangles = mesh.triangles.ToArray(),
                Edges = CanonicalEdges(NativeArrayOrEmpty(mesh.edges)),
                VertexToVertexRanges = vertexToVertexRanges,
                VertexToVertexData = vertexToVertexData.Select(value => (int)value).ToArray(),
                VertexToTriangleRecords = vertexToTriangleRecords,
                LocalNormals = mesh.localNormals.ToArray(),
                LocalTangents = mesh.localTangents.ToArray(),
                VertexBindPosePositions = NativeArrayOrEmpty(mesh.vertexBindPosePositions),
                VertexBindPoseRotations = bindPoseRotations.Select(value => value.value).ToArray(),
            };
        }

        private static T[] NativeArrayOrEmpty<T>(NativeArray<T> values) where T : unmanaged
        {
            return values.IsCreated ? values.ToArray() : Array.Empty<T>();
        }

        private static IEnumerable<OracleCase> Cases()
        {
            yield return new OracleCase
            {
                Id = "mesh_baseline_single_fixed_triangle_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x81, 0x82, 0x82 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = T((0, 1, 2)),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Single fixed triangle and source parent-local orientation basis.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_no_fixed_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x82, 0x82, 0x82 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = T((0, 1, 2)),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "No Fixed vertex; baseline pose arrays remain clear-memory initialized.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_disconnected_island_001",
                Positions = P((0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (2, 3)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }, new[] { 3 }, new[] { 2 }),
                Note = "Move-only disconnected island is not assigned to a baseline.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_multi_fixed_distance_001",
                Positions = P((0, 0, 0), (3, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 0, 1 }),
                Note = "Move vertex selects the closer Fixed parent.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_move_angle_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1.5f, 0), (2, 0.1f, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (1, 3), (2, 3)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 3 }, new[] { 0, 3 }, new[] { 1, 2 }),
                Note = "Second wave selects the Move parent with the shallower continuation angle.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_same_frontier_parent_001",
                Positions = P((0, 0, 0), (1, 0, 0), (2, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Earlier Move in one sorted frontier can parent a later Move immediately.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_zero_distance_001",
                Positions = P((0, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }),
                Note = "Zero parent-local distance finalizes VertexAttribute.ZeroDistance.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_equal_cost_low_first_001",
                Positions = P((-1, 0, 0), (1, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 0, 1 }),
                Note = "Equal Fixed cost with lower vertex index enumerated first.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_equal_cost_high_first_001",
                Positions = P((-1, 0, 0), (1, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 1, 0 }),
                CompareToHoTools = false,
                Note = "Equal Fixed cost with higher vertex index enumerated first; source keeps first enumerated.",
            };
        }

        private static IEnumerable<ProxyCase> ProxyCases()
        {
            yield return new ProxyCase
            {
                Id = "mesh_proxy_consistent_winding_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Single triangle keeps winding and ORs Triangle bit into Fixed/Move attributes.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_reversed_neighbor_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Normals = Fill3(4, (0, 0, 1)),
                Tangents = Fill3(4, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (1, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2), (1, 2, 3)),
                Note = "Neighbor triangle starts reversed across a shared edge and is normalized by OptimizeTriangleDirection.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_layer_boundary_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 1, 1)),
                Normals = Fill3(4, (0, 0, 1)),
                Tangents = Fill3(4, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (1, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2), (1, 2, 3)),
                Note = "Shared-edge triangles above SameSurfaceAngle remain separate direction layers.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_uv_tangent_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 1), (0, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Triangle tangent is generated from final positions and per-vertex UVs.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_uv_zero_area_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 1), (2, 2)),
                Attributes = new byte[] { 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Zero UV area follows MathUtility.TriangleTangent area fallback without topology changes.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_vertex_triangle_cap_001",
                Positions = P(
                    (0, 0, 0),
                    (1, 0, 0),
                    (0.7071068f, 0.7071068f, 0),
                    (0, 1, 0),
                    (-0.7071068f, 0.7071068f, 0),
                    (-1, 0, 0),
                    (-0.7071068f, -0.7071068f, 0),
                    (0, -1, 0),
                    (0.7071068f, -0.7071068f, 0)
                ),
                Normals = Fill3(9, (0, 0, 1)),
                Tangents = Fill3(9, (1, 0, 0)),
                Uvs = UV(
                    (0, 0),
                    (1, 0),
                    (0.7071068f, 0.7071068f),
                    (0, 1),
                    (-0.7071068f, 0.7071068f),
                    (-1, 0),
                    (-0.7071068f, -0.7071068f),
                    (0, -1),
                    (0.7071068f, -0.7071068f)
                ),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02 },
                Triangles = T(
                    (0, 1, 2),
                    (0, 2, 3),
                    (0, 3, 4),
                    (0, 4, 5),
                    (0, 5, 6),
                    (0, 6, 7),
                    (0, 7, 8),
                    (0, 8, 1)
                ),
                Note = "A vertex touched by eight triangles keeps only seven vertexToTriangles records.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_triangle_loose_line_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0)),
                Normals = Fill3(5, (0, 0, 1)),
                Tangents = Fill3(5, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (2, 0), (3, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02, 0x02 },
                Lines = E((3, 4)),
                Triangles = T((0, 1, 2)),
                Note = "Explicit line edge is unioned with triangle edges while line-only vertices keep no Triangle bit.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_attribute_or_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1)),
                Attributes = new byte[] { 0x11, 0x12, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Triangle membership OR preserves Fixed/Move and DisableCollision bits.",
            };
        }

        private static IEnumerable<DistanceCase> DistanceCases()
        {
            yield return new DistanceCase
            {
                Id = "distance_parent_horizontal_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Parent edges are vertical positive rest; the sibling edge is horizontal negative rest.",
            };
            yield return new DistanceCase
            {
                Id = "distance_square_shear_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "Coplanar square adds the missing opposite diagonal 0-3 as bidirectional horizontal shear.",
            };
            yield return new DistanceCase
            {
                Id = "distance_shear_normal_reject_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 0, 1)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "A folded triangle pair fails the abs(normal dot) shear threshold.",
            };
            yield return new DistanceCase
            {
                Id = "distance_shear_ratio_reject_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (3, 3, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "A coplanar pair with mismatched diagonals fails the 0.3 length-ratio threshold.",
            };
            yield return new DistanceCase
            {
                Id = "distance_invalid_filters_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Attributes = new byte[] { 0x00, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, -1, -1, -1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "Ordinary edges touching Invalid vertex 0 are filtered, but shear 0-3 is still emitted.",
            };
            yield return new DistanceCase
            {
                Id = "distance_all_fixed_empty_001",
                Positions = P((0, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01 },
                Parents = new[] { -1, -1 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }),
                Note = "An all-Fixed ordinary edge produces no Distance arrays.",
            };
            yield return new DistanceCase
            {
                Id = "distance_zero_kind_loss_001",
                Positions = P((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Vertical and horizontal distances below 1e-8 both serialize as positive zero.",
            };
        }

        private static IEnumerable<DistanceRuntimeCase> DistanceRuntimeCases()
        {
            yield return new DistanceRuntimeCase
            {
                Id = "distance_runtime_nonzero_then_zero_001",
                Targets = new[] { 1, 2 },
                RestSigned = new[] { 1.0f, 0.0f },
                Note = "A trailing zero-distance record overwrites the earlier nonzero correction before averaging.",
            };
            yield return new DistanceRuntimeCase
            {
                Id = "distance_runtime_zero_then_nonzero_001",
                Targets = new[] { 2, 1 },
                RestSigned = new[] { 0.0f, 1.0f },
                Note = "The same records in reverse order preserve the zero correction and then add nonzero correction.",
            };
        }

        private static IEnumerable<BendingCase> BendingCases()
        {
            yield return new BendingCase
            {
                Id = "bending_flat_dihedral_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "Flat pair emits one directional dihedral record and dir==0 maps to sign +1.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_100_double_001",
                Positions = FoldedPair(100.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A 100 degree pair emits bending first and volume second for the same ordered quad.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_89_9_bending_only_001",
                Positions = FoldedPair(89.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below 90 degrees emits bending but not volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_119_9_double_001",
                Positions = FoldedPair(119.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below the strict 120 degree cutoff still emits bending and volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_120_1_volume_only_001",
                Positions = FoldedPair(120.1f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair above the strict 120 degree cutoff emits only volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_130_volume_only_001",
                Positions = FoldedPair(130.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A 130 degree pair is excluded from bending but retained as volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_178_9_volume_only_001",
                Positions = FoldedPair(178.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below the 179 degree inclusive maximum still emits volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_above_179_empty_001",
                Positions = FoldedPair(179.5f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "An angle above 179 degrees is excluded from both bending and volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_all_fixed_empty_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x01, 0x01, 0x01, 0x01 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A four-Fixed pair returns success with empty main arrays.",
            };
            yield return new BendingCase
            {
                Id = "bending_invalid_empty_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x00, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "Any Invalid vertex filters the complete quad.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_100_scaled_world_001",
                Positions = FoldedPair(100.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                InitLocalToWorld = float4x4.Scale(new float3(2.0f)),
                Note = "Uniform initial world scale leaves angle unchanged and scales signed volume by eight.",
            };
            yield return new BendingCase
            {
                Id = "bending_tetra_volume_first_wins_001",
                Positions = P((1, 1, 1), (-1, -1, 1), (-1, 1, -1), (1, -1, -1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
                Note = "Multiple edge roles share one unordered four-vertex volume key; only the first volume survives.",
            };
            yield return new BendingCase
            {
                Id = "bending_no_triangles_null_001",
                Positions = P((0, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x02, 0x02 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Note = "TriangleCount zero returns null rather than a success-empty ConstraintData.",
            };
        }

        private static IEnumerable<BendingRuntimeCase> BendingRuntimeCases()
        {
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_single_fixed_sum_001",
                OrderedQuads = new[] { new int4(1, 0, 2, 3) },
                RestAngleOrVolume = new[] { 0.0f },
                SignOrVolume = new sbyte[] { 1 },
                NextPositions = FoldedPair(30.0f),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Note = "One directional dihedral contributes to all scratch slots; Sum keeps Fixed vertex 0 unchanged and clears every slot.",
            };
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_double_positive_scale_001",
                OrderedQuads = new[]
                {
                    new int4(1, 0, 2, 3),
                    new int4(1, 0, 2, 3),
                },
                RestAngleOrVolume = new[] { 1.74532926f, 164.134628f },
                SignOrVolume = new sbyte[] { -1, 100 },
                NextPositions = FoldedPair(70.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                ScaleRatio = 1.25f,
                Note = "Bending and volume both contribute; Sum averages two fixed-point scratch records per vertex.",
            };
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_double_negative_scale_001",
                OrderedQuads = new[]
                {
                    new int4(1, 0, 2, 3),
                    new int4(1, 0, 2, 3),
                },
                RestAngleOrVolume = new[] { 1.74532926f, 164.134628f },
                SignOrVolume = new sbyte[] { -1, 100 },
                NextPositions = FoldedPair(70.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                ScaleRatio = 1.25f,
                NegativeScaleSign = -1.0f,
                Note = "The same records consume negativeScaleSign in both directional dihedral and volume paths.",
            };
        }

        private static float3[] FoldedPair(float degrees)
        {
            float radians = math.radians(degrees);
            return P(
                (0, 1, 0),
                (0, -math.cos(radians), -math.sin(radians)),
                (0, 0, 0),
                (1, 0, 0)
            );
        }

        private static float3[] P(params (float x, float y, float z)[] values)
        {
            return values.Select(value => new float3(value.x, value.y, value.z)).ToArray();
        }

        private static float3[] Fill3(int count, (float x, float y, float z) value)
        {
            return Enumerable.Repeat(new float3(value.x, value.y, value.z), count).ToArray();
        }

        private static float2[] UV(params (float x, float y)[] values)
        {
            return values.Select(value => new float2(value.x, value.y)).ToArray();
        }

        private static int2[] E(params (int x, int y)[] values)
        {
            return values.Select(value => new int2(value.x, value.y)).ToArray();
        }

        private static int3[] T(params (int x, int y, int z)[] values)
        {
            return values.Select(value => new int3(value.x, value.y, value.z)).ToArray();
        }

        private static int[][] A(params int[][] values)
        {
            return values;
        }

        private static int2[] CanonicalEdges(IEnumerable<int2> values)
        {
            return values
                .Select(value => value.x <= value.y ? value : new int2(value.y, value.x))
                .GroupBy(value => value.x.ToString(CultureInfo.InvariantCulture) + ":" + value.y.ToString(CultureInfo.InvariantCulture))
                .Select(group => group.First())
                .OrderBy(value => value.x)
                .ThenBy(value => value.y)
                .ToArray();
        }

        private static string BuildJson(OracleCase oracleCase, OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(oracleCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateMeshBaseLine",
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateBaseLinePose",
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateVertexRootAndDepth"
                )
            );
            Property(text, 2, "scope", Quote(oracleCase.Note));
            Property(text, 2, "comparison", ComparisonJson(oracleCase));
            Property(text, 2, "input", InputJson(oracleCase));
            Property(text, 2, "expected", ExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildProxyJson(ProxyCase proxyCase, ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(proxyCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::ConvertProxyMesh")
            );
            Property(text, 2, "scope", Quote(proxyCase.Note));
            Property(text, 2, "comparison", ProxyComparisonJson());
            Property(text, 2, "input", ProxyInputJson(proxyCase));
            Property(text, 2, "expected", ProxyOnlyExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildDistanceJson(DistanceCase distanceCase, DistanceDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(distanceCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Cloth/Constraints/DistanceConstraint.cs::CreateData",
                    "Runtime/Utility/Data/DataUtility.cs::Pack12_20"
                )
            );
            Property(text, 2, "scope", Quote(distanceCase.Note));
            Property(text, 2, "comparison", DistanceComparisonJson());
            Property(text, 2, "input", DistanceInputJson(distanceCase));
            Property(text, 2, "expected", DistanceExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildDistanceRuntimeJson(
            DistanceRuntimeCase runtimeCase,
            DistanceRuntimeDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(runtimeCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Cloth/Constraints/DistanceConstraint.cs::SolverConstraint")
            );
            Property(text, 2, "scope", Quote(runtimeCase.Note));
            Property(text, 2, "comparison", DistanceRuntimeComparisonJson());
            Property(text, 2, "input", DistanceRuntimeInputJson(runtimeCase));
            Property(text, 2, "expected", DistanceRuntimeExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildBendingJson(BendingCase bendingCase, BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(bendingCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::CreateData",
                    "Runtime/Utility/Data/DataUtility.cs::Pack64"
                )
            );
            Property(text, 2, "scope", Quote(bendingCase.Note));
            Property(text, 2, "comparison", BendingComparisonJson());
            Property(text, 2, "input", BendingInputJson(bendingCase));
            Property(text, 2, "expected", BendingExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildBendingRuntimeJson(
            BendingRuntimeCase runtimeCase,
            BendingRuntimeDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(runtimeCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SolverConstraint",
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SumConstraint"
                )
            );
            Property(text, 2, "scope", Quote(runtimeCase.Note));
            Property(text, 2, "comparison", BendingRuntimeComparisonJson());
            Property(text, 2, "input", BendingRuntimeInputJson(runtimeCase));
            Property(text, 2, "expected", BendingRuntimeExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildParticleStepJson(ParticleStepDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote("particle_step_gravity_damping_001"));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateParticles")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Zero-inertia/wind/collision particle prediction locks velocityWeight, damping, gravity, fixed pose, and scratch clear order.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_power", "[1,1,0.5,1]");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_interpolation", "1");
            Property(text, 4, "velocity_weight", "0.8");
            Property(text, 4, "gravity_ratio", "0.75");
            Property(text, 4, "scale_ratio", "1.5");
            Property(text, 4, "gravity", "9");
            Property(text, 4, "gravity_direction", "[0,-1,0]");
            Property(text, 4, "damping_samples", "[0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2,0.2]");
            Property(text, 4, "depths", "[0.5,0]");
            Property(text, 4, "attributes", "[2,1]");
            Property(text, 4, "animated_positions", "[[0,0,0],[10,0,0]]");
            Property(text, 4, "old_positions", "[[1,2,3],[4,5,6]]");
            Property(text, 4, "velocities", "[[2,-1,0.5],[9,9,9]]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "base_positions", ArrayJson(dump.BasePositions, Vector3Json));
            Property(text, 4, "next_positions", ArrayJson(dump.NextPositions, Vector3Json));
            Property(text, 4, "velocity_positions", ArrayJson(dump.VelocityPositions, Vector3Json));
            Property(text, 4, "temp_vector_a", ArrayJson(dump.TempVectorA, Vector3Json));
            Property(text, 4, "temp_vector_b", ArrayJson(dump.TempVectorB, Vector3Json));
            Property(text, 4, "temp_counts", NumberArray(dump.TempCounts));
            Property(text, 4, "temp_floats", ArrayJson(dump.TempFloats, FloatJson), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildParticleInertiaStepJson(ParticleInertiaStepDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote("particle_step_inertia_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateParticles")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates depth-weighted Center inertia translation/rotation, velocity-reference shift, velocity rotation, and step-basic animated pose before forces and constraints.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_power", "[1,1,0,1]");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_interpolation", "1");
            Property(text, 4, "velocity_weight", "0.75");
            Property(text, 4, "depth", "0.5");
            Property(text, 4, "depth_inertia", "0.8");
            Property(text, 4, "old_world_position", "[1,1,1]");
            Property(text, 4, "step_vector", "[2,0,0]");
            Property(text, 4, "step_rotation_axis_angle", "{\"axis\":[0,0,1],\"degrees\":90}");
            Property(text, 4, "inertia_vector", "[0.5,0,0]");
            Property(text, 4, "inertia_rotation_axis_angle", "{\"axis\":[0,0,1],\"degrees\":30}");
            Property(text, 4, "animated_position", "[9,9,9]");
            Property(text, 4, "animated_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_animated_position", "[8,8,8]");
            Property(text, 4, "old_position", "[3,2,1]");
            Property(text, 4, "velocity", "[1,0,0]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "base_positions", ArrayJson(dump.BasePositions, Vector3Json));
            Property(text, 4, "base_rotations_xyzw", ArrayJson(dump.BaseRotations, QuaternionJson));
            Property(text, 4, "step_basic_positions", ArrayJson(dump.StepBasicPositions, Vector3Json));
            Property(text, 4, "step_basic_rotations_xyzw", ArrayJson(dump.StepBasicRotations, QuaternionJson));
            Property(text, 4, "next_positions", ArrayJson(dump.NextPositions, Vector3Json));
            Property(text, 4, "velocity_positions", ArrayJson(dump.VelocityPositions, Vector3Json), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildBaselineStepPoseJson(BaselineStepPoseDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("particle_step_baseline_pose_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text, 2, "source",
                SourceJson(
                    "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationStepUpdateBaseLinePose"
                )
            );
            Property(
                text, 2, "scope",
                Quote("Isolates parent-first baseline step-basic reconstruction, nonuniform team scale, animation-pose blending, and an uncovered Move island at positive scale.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "attributes", "[1,2,2,2]");
            Property(text, 4, "parent_indices", "[-1,0,1,-1]");
            Property(text, 4, "baseline_ranges", "[[0,3]]");
            Property(text, 4, "baseline_data", "[0,1,2]");
            Property(text, 4, "vertex_local_positions", "[[0,0,0],[1,0,0],[0,1,0],[0,0,0]]");
            Property(text, 4, "vertex_local_rotation_axis_angles", "[null,{\"axis\":[0,0,1],\"degrees\":30},{\"axis\":[1,0,0],\"degrees\":20},null]");
            Property(text, 4, "base_positions", "[[10,0,0],[12,4,0],[-1,8,2],[7,7,7]]");
            Property(text, 4, "base_rotation_axis_angles", "[{\"axis\":[0,1,0],\"degrees\":10},{\"axis\":[0,1,0],\"degrees\":80},{\"axis\":[0,0,1],\"degrees\":-25},{\"axis\":[1,0,0],\"degrees\":15}]");
            Property(text, 4, "initial_scale", "[2,1,0.5]");
            Property(text, 4, "scale_ratio", "1.5");
            Property(text, 4, "negative_scale_direction", "[1,1,1]");
            Property(text, 4, "negative_scale_quaternion_value", "[1,1,1,1]");
            Property(text, 4, "animation_pose_ratio", "0.25", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "step_basic_positions", ArrayJson(dump.StepBasicPositions, Vector3Json));
            Property(
                text, 4, "step_basic_rotations_xyzw",
                ArrayJson(dump.StepBasicRotations, QuaternionJson), false
            );
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildFrameResetJson(FrameResetDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("frame_reset_pose_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Utility/Math/MathUtility.cs::ToRotation",
                    "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationPreTeamUpdate"
                )
            );
            Property(text, 2, "expected", FrameResetExpectedJson(dump), false);
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterStaticJson(CenterStaticDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_static_fixed_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::ProxyCreateFixedListAndAABB",
                    "Runtime/Cloth/Constraints/InertiaConstraint.cs::CreateData"
                )
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "positions", "[[0,0,0],[2,0,0],[0,2,0],[0,0,3]]");
            Property(text, 4, "attributes", "[1,2,1,1]");
            Property(text, 4, "triangles", "[[0,1,2]]");
            Property(text, 4, "world_gravity_direction", Vector3Json(math.normalize(new float3(1, -2, 0.5f))), false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "fixed_indices", NumberArray(dump.FixedIndices));
            Property(text, 4, "local_center_position", Vector3Json(dump.LocalCenterPosition));
            Property(text, 4, "initial_local_gravity_direction", Vector3Json(dump.InitialLocalGravityDirection), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterFrameShiftJson(
            string caseId,
            string scope,
            float movementSpeedLimit,
            float rotationSpeedLimit,
            CenterFrameShiftDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote(caseId));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote(scope)
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "world_inertia", "0.25");
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", FloatJson(movementSpeedLimit));
            Property(text, 4, "rotation_speed_limit", FloatJson(rotationSpeedLimit));
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterKeepTeleportJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_keep_teleport_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates configured Keep teleport detection before smoothing, with unit positive scale and no fixed list, anchor, speed limits, synchronization, culling, skip, or stabilization effects.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "world_inertia", "1");
            Property(text, 4, "movement_inertia_smoothing", "0.5");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "teleport_mode", "2");
            Property(text, 4, "teleport_distance", "5");
            Property(text, 4, "teleport_rotation", "180");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "smoothing_velocity", "[2,0,0]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "keep_teleport", dump.KeepTeleport ? "true" : "false");
            Property(text, 4, "reset_teleport", dump.Reset ? "true" : "false");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterResetTeleportJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_reset_teleport_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates configured Reset teleport detection and Center reset before particle reset, with unit positive scale and no fixed list, anchor, speed limits, synchronization, culling, skip, or stabilization effects.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "world_inertia", "1");
            Property(text, 4, "movement_inertia_smoothing", "0.5");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "teleport_mode", "1");
            Property(text, 4, "teleport_distance", "5");
            Property(text, 4, "teleport_rotation", "180");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "smoothing_velocity", "[2,0,0]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "keep_teleport", dump.KeepTeleport ? "true" : "false");
            Property(text, 4, "reset_teleport", dump.Reset ? "true" : "false");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterAnchorShiftJson(
            string caseId,
            string scope,
            float worldInertia,
            float movementSpeedLimit,
            float rotationSpeedLimit,
            CenterFrameShiftDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote(caseId));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote(scope)
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "anchor_inertia", "0.25");
            Property(text, 4, "world_inertia", FloatJson(worldInertia));
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", FloatJson(movementSpeedLimit));
            Property(text, 4, "rotation_speed_limit", FloatJson(rotationSpeedLimit));
            Property(text, 4, "old_component_world_position", "[1,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[0,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_anchor_world_position", "[0,0,0]");
            Property(text, 4, "old_anchor_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "anchor_world_position", "[0,0,1]");
            Property(text, 4, "anchor_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "anchor_component_local_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[1,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterSmoothingShiftJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_smoothing_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates positive-scale movement-inertia smoothing velocity update and cancellation with world inertia, fixed list, anchor, limits, teleport, synchronization, culling, skip, and stabilization disabled.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "is_running", "true");
            Property(text, 4, "world_inertia", "1");
            Property(text, 4, "movement_inertia_smoothing", "0.5");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "smoothing_velocity", "[2,0,0]");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterTimeScaleShiftJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_time_scale_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates positive time-scale cancellation after world inertia with fixed list, anchor, smoothing, limits, teleport, synchronization, culling, skip, and stabilization disabled.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.05");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "0.5");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "skip_count", "0");
            Property(text, 4, "world_inertia", "0.75");
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterSkipCountShiftJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_skip_count_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Manager/Team/TeamManager.cs::AlwaysTeamUpdatePostJob.Execute",
                    "Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind"
                )
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates positive-scale update-skip cancellation with world inertia, stabilization, time-scale reduction, fixed list, anchor, smoothing, limits, teleport, synchronization, and culling disabled.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.02");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "max_simulation_count_per_frame", "3");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "skip_count", "2");
            Property(text, 4, "world_inertia", "1");
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "update_count", dump.UpdateCount.ToString(CultureInfo.InvariantCulture));
            Property(text, 4, "skip_count", dump.SkipCount.ToString(CultureInfo.InvariantCulture));
            Property(text, 4, "time", FloatJson(dump.Time));
            Property(text, 4, "old_time", FloatJson(dump.OldTime));
            Property(text, 4, "now_update_time", FloatJson(dump.NowUpdateTime));
            Property(text, 4, "old_update_time", FloatJson(dump.OldUpdateTime));
            Property(text, 4, "frame_update_time", FloatJson(dump.FrameUpdateTime));
            Property(text, 4, "frame_old_time", FloatJson(dump.FrameOldTime));
            Property(
                text, 4, "step_frame_interpolations",
                ArrayJson(dump.StepFrameInterpolations, FloatJson)
            );
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterFixedShiftJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_fixed_center_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates positive-scale world-inertia frame shift while the current Center frame is derived from a Fixed particle instead of the component transform.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "1");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "skip_count", "0");
            Property(text, 4, "world_inertia", "0.25");
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "fixed_indices", "[0]");
            Property(text, 4, "fixed_world_positions", "[[12,2,0]]");
            Property(text, 4, "fixed_world_rotations_xyzw", "[[0,0.707106769,0,0.707106769]]");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "frame_world_position", "[12,2,0]");
            Property(text, 4, "frame_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterZeroTimeScaleShiftJson(CenterFrameShiftDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_zero_time_scale_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates zero-time-scale full cancellation and zero moving speed without running a simulation step.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0");
            Property(text, 4, "frame_delta_time", "0.1");
            Property(text, 4, "now_time_scale", "0");
            Property(text, 4, "velocity_weight", "1");
            Property(text, 4, "skip_count", "0");
            Property(text, 4, "world_inertia", "0.75");
            Property(text, 4, "movement_inertia_smoothing", "0");
            Property(text, 4, "movement_speed_limit", "-1");
            Property(text, 4, "rotation_speed_limit", "-1");
            Property(text, 4, "old_component_world_position", "[0,0,0]");
            Property(text, 4, "old_component_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "old_component_world_scale", "[1,1,1]");
            Property(text, 4, "component_world_position", "[10,0,0]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "component_world_scale", "[1,1,1]");
            Property(text, 4, "old_frame_world_position", "[1,0,0]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "now_world_position", "[2,0,0]");
            Property(text, 4, "now_world_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "frame_moving_direction", Vector3Json(dump.FrameMovingDirection));
            Property(text, 4, "frame_moving_speed", FloatJson(dump.FrameMovingSpeed));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildCenterStepJson(CenterStepDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_step_inertia_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Manager/Team/TeamManager.cs::SimulationStepTeamUpdate")
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates frame interpolation, local inertia limits, scale ratio, gravity falloff, velocity stabilization, and blend weight with wind disabled.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "simulation_delta_time", "0.1");
            Property(text, 4, "update_index", "0");
            Property(text, 4, "update_count", "1");
            Property(text, 4, "time", "1.4");
            Property(text, 4, "frame_old_time", "1");
            Property(text, 4, "now_update_time_before_step", "1.1");
            Property(text, 4, "old_frame_world_position", "[0,0,0]");
            Property(text, 4, "frame_world_position", "[4,2,-2]");
            Property(text, 4, "old_frame_world_rotation_xyzw", "[0,0,0,1]");
            Property(text, 4, "frame_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":90}");
            Property(text, 4, "old_frame_world_scale", "[1,1,1]");
            Property(text, 4, "frame_world_scale", "[2,1,1]");
            Property(text, 4, "init_scale", "[1,1,1]");
            Property(text, 4, "negative_scale_direction", "[1,-1,1]");
            Property(text, 4, "initial_local_gravity_direction", "[1,0,0]");
            Property(text, 4, "world_gravity_direction", "[1,0,0]");
            Property(text, 4, "gravity", "9");
            Property(text, 4, "gravity_falloff", "0.6");
            Property(text, 4, "local_inertia", "0.75");
            Property(text, 4, "local_movement_speed_limit", "5");
            Property(text, 4, "local_rotation_speed_limit", "90");
            Property(text, 4, "velocity_weight_before_step", "0.2");
            Property(text, 4, "stabilization_time_after_reset", "0.5");
            Property(text, 4, "distance_weight", "0.8");
            Property(text, 4, "parameter_blend_weight", "0.7", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "frame_interpolation", FloatJson(dump.FrameInterpolation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "step_vector", Vector3Json(dump.StepVector));
            Property(text, 4, "step_rotation_xyzw", QuaternionJson(dump.StepRotation));
            Property(text, 4, "step_move_inertia_ratio", FloatJson(dump.StepMoveInertiaRatio));
            Property(text, 4, "step_rotation_inertia_ratio", FloatJson(dump.StepRotationInertiaRatio));
            Property(text, 4, "inertia_vector", Vector3Json(dump.InertiaVector));
            Property(text, 4, "inertia_rotation_xyzw", QuaternionJson(dump.InertiaRotation));
            Property(text, 4, "angular_velocity", FloatJson(dump.AngularVelocity));
            Property(text, 4, "rotation_axis", Vector3Json(dump.RotationAxis));
            Property(text, 4, "scale_ratio", FloatJson(dump.ScaleRatio));
            Property(text, 4, "gravity_dot", FloatJson(dump.GravityDot));
            Property(text, 4, "gravity_ratio", FloatJson(dump.GravityRatio));
            Property(text, 4, "velocity_weight", FloatJson(dump.VelocityWeight));
            Property(text, 4, "blend_weight", FloatJson(dump.BlendWeight), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildNegativeScaleTeleportJson(NegativeScaleTeleportDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_negative_scale_x_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind",
                    "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationPreTeamUpdate"
                )
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates an X-axis component scale-sign transition, Center-space teleport matrix construction, and particle-history transformation before inertia shift.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "old_component_world_position", "[1,2,3]");
            Property(text, 4, "old_component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":20}");
            Property(text, 4, "old_component_world_scale", "[1,2,0.5]");
            Property(text, 4, "component_world_position", "[4,-2,5]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":65}");
            Property(text, 4, "component_world_scale", "[-2,1.5,0.75]");
            Property(text, 4, "old_frame_world_position", "[-2,1,4]");
            Property(text, 4, "old_frame_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":-30}");
            Property(text, 4, "old_frame_world_scale", "[1,2,0.5]");
            Property(text, 4, "old_anchor_position", "[2,-3,1]");
            Property(text, 4, "smoothing_velocity", "[1,2,-1]");
            Property(text, 4, "old_position", "[2,3,4]");
            Property(text, 4, "old_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":30}");
            Property(text, 4, "animation_old_position", "[5,-1,2]");
            Property(text, 4, "animation_old_rotation_axis_angle", "{\"axis\":[1,0,0],\"degrees\":45}");
            Property(text, 4, "display_position", "[-2,1,3]");
            Property(text, 4, "velocity", "[1,2,-1]");
            Property(text, 4, "real_velocity", "[-1,0.5,2]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "negative_scale_sign", FloatJson(dump.NegativeScaleSign));
            Property(text, 4, "negative_scale_direction", Vector3Json(dump.NegativeScaleDirection));
            Property(text, 4, "negative_scale_change", Vector3Json(dump.NegativeScaleChange));
            Property(text, 4, "negative_scale_triangle_sign", Vector2Json(dump.NegativeScaleTriangleSign));
            Property(text, 4, "negative_scale_quaternion_value", Vector4Json(dump.NegativeScaleQuaternionValue));
            Property(text, 4, "negative_scale_matrix_columns", Matrix4x4ColumnsJson(dump.NegativeScaleMatrix));
            Property(text, 4, "old_component_world_position", Vector3Json(dump.OldComponentWorldPosition));
            Property(text, 4, "old_component_world_scale", Vector3Json(dump.OldComponentWorldScale));
            Property(text, 4, "old_anchor_position", Vector3Json(dump.OldAnchorPosition));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity));
            Property(text, 4, "old_position", Vector3Json(dump.OldPosition));
            Property(text, 4, "old_rotation_xyzw", QuaternionJson(dump.OldRotation));
            Property(text, 4, "animation_old_position", Vector3Json(dump.AnimationOldPosition));
            Property(text, 4, "animation_old_rotation_xyzw", QuaternionJson(dump.AnimationOldRotation));
            Property(text, 4, "display_position", Vector3Json(dump.DisplayPosition));
            Property(text, 4, "velocity", Vector3Json(dump.Velocity));
            Property(text, 4, "real_velocity", Vector3Json(dump.RealVelocity), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string BuildResetNegativeScaleTeleportJson(
            NegativeScaleTeleportDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "case_id", Quote("center_frame_shift_reset_negative_scale_x_001"));
            Property(text, 2, "oracle_tier", Quote("A"));
            Property(text, 2, "mc2_version", Quote(MC2Version));
            Property(text, 2, "mc2_commit", Quote(MC2Commit));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind",
                    "Runtime/Manager/Simulation/SimulationManagerNormal.cs::SimulationPreTeamUpdate"
                )
            );
            Property(
                text,
                2,
                "scope",
                Quote("Isolates configured Reset teleport after an X-axis scale-sign transition and proves particle reset takes precedence over the negative-scale matrix.")
            );
            text.AppendLine("  \"input\": {");
            Property(text, 4, "teleport_mode", "1");
            Property(text, 4, "teleport_distance", "1000");
            Property(text, 4, "teleport_rotation", "30");
            Property(text, 4, "initial_scale", "[1,1,1]");
            Property(text, 4, "old_negative_scale_direction", "[1,1,1]");
            Property(text, 4, "old_component_world_position", "[1,2,3]");
            Property(text, 4, "old_component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":20}");
            Property(text, 4, "old_component_world_scale", "[1,2,0.5]");
            Property(text, 4, "component_world_position", "[4,-2,5]");
            Property(text, 4, "component_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":65}");
            Property(text, 4, "component_world_scale", "[-2,1.5,0.75]");
            Property(text, 4, "old_frame_world_position", "[-2,1,4]");
            Property(text, 4, "old_frame_world_rotation_axis_angle", "{\"axis\":[0,1,0],\"degrees\":-30}");
            Property(text, 4, "old_frame_world_scale", "[1,2,0.5]");
            Property(text, 4, "old_anchor_position", "[2,-3,1]");
            Property(text, 4, "smoothing_velocity", "[1,2,-1]");
            Property(text, 4, "animated_position", "[8,1,-2]");
            Property(text, 4, "animated_rotation_xyzw", "[0,0,0,1]", false);
            text.AppendLine("  },");
            text.AppendLine("  \"expected\": {");
            Property(text, 4, "keep_teleport", dump.KeepTeleport ? "true" : "false");
            Property(text, 4, "reset_teleport", dump.Reset ? "true" : "false");
            Property(text, 4, "inertia_shift", dump.InertiaShift ? "true" : "false");
            Property(text, 4, "negative_scale_teleport", dump.NegativeScaleTeleport ? "true" : "false");
            Property(text, 4, "negative_scale_sign", FloatJson(dump.NegativeScaleSign));
            Property(text, 4, "negative_scale_direction", Vector3Json(dump.NegativeScaleDirection));
            Property(text, 4, "negative_scale_change", Vector3Json(dump.NegativeScaleChange));
            Property(text, 4, "negative_scale_triangle_sign", Vector2Json(dump.NegativeScaleTriangleSign));
            Property(text, 4, "negative_scale_quaternion_value", Vector4Json(dump.NegativeScaleQuaternionValue));
            Property(text, 4, "negative_scale_matrix_columns", Matrix4x4ColumnsJson(dump.NegativeScaleMatrix));
            Property(text, 4, "old_component_world_position", Vector3Json(dump.OldComponentWorldPosition));
            Property(text, 4, "old_component_world_scale", Vector3Json(dump.OldComponentWorldScale));
            Property(text, 4, "frame_component_shift_vector", Vector3Json(dump.FrameComponentShiftVector));
            Property(text, 4, "frame_component_shift_rotation_xyzw", QuaternionJson(dump.FrameComponentShiftRotation));
            Property(text, 4, "old_frame_world_position", Vector3Json(dump.OldFrameWorldPosition));
            Property(text, 4, "old_frame_world_rotation_xyzw", QuaternionJson(dump.OldFrameWorldRotation));
            Property(text, 4, "now_world_position", Vector3Json(dump.NowWorldPosition));
            Property(text, 4, "now_world_rotation_xyzw", QuaternionJson(dump.NowWorldRotation));
            Property(text, 4, "frame_world_position", Vector3Json(dump.FrameWorldPosition));
            Property(text, 4, "frame_world_rotation_xyzw", QuaternionJson(dump.FrameWorldRotation));
            Property(text, 4, "smoothing_velocity", Vector3Json(dump.SmoothingVelocity));
            Property(text, 4, "next_position", Vector3Json(dump.NextPosition));
            Property(text, 4, "old_position", Vector3Json(dump.OldPosition));
            Property(text, 4, "old_rotation_xyzw", QuaternionJson(dump.OldRotation));
            Property(text, 4, "base_position", Vector3Json(dump.BasePosition));
            Property(text, 4, "base_rotation_xyzw", QuaternionJson(dump.BaseRotation));
            Property(text, 4, "animation_old_position", Vector3Json(dump.AnimationOldPosition));
            Property(text, 4, "animation_old_rotation_xyzw", QuaternionJson(dump.AnimationOldRotation));
            Property(text, 4, "velocity_reference_position", Vector3Json(dump.VelocityReferencePosition));
            Property(text, 4, "display_position", Vector3Json(dump.DisplayPosition));
            Property(text, 4, "velocity", Vector3Json(dump.Velocity));
            Property(text, 4, "real_velocity", Vector3Json(dump.RealVelocity));
            Property(text, 4, "friction", FloatJson(dump.Friction));
            Property(text, 4, "static_friction", FloatJson(dump.StaticFriction));
            Property(text, 4, "collision_normal", Vector3Json(dump.CollisionNormal), false);
            text.AppendLine("  }");
            text.Append("}");
            return text.ToString();
        }

        private static string FrameResetExpectedJson(FrameResetDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "world_positions", ArrayJson(dump.WorldPositions, Vector3Json));
            Property(text, 4, "world_rotations_xyzw", ArrayJson(dump.WorldRotations, QuaternionJson));
            Property(text, 4, "next_positions", ArrayJson(dump.NextPositions, Vector3Json));
            Property(text, 4, "old_positions", ArrayJson(dump.OldPositions, Vector3Json));
            Property(text, 4, "old_rotations_xyzw", ArrayJson(dump.OldRotations, QuaternionJson));
            Property(text, 4, "base_positions", ArrayJson(dump.BasePositions, Vector3Json));
            Property(text, 4, "base_rotations_xyzw", ArrayJson(dump.BaseRotations, QuaternionJson));
            Property(text, 4, "animation_old_positions", ArrayJson(dump.AnimationOldPositions, Vector3Json));
            Property(text, 4, "animation_old_rotations_xyzw", ArrayJson(dump.AnimationOldRotations, QuaternionJson));
            Property(text, 4, "velocity_reference_positions", ArrayJson(dump.VelocityReferencePositions, Vector3Json));
            Property(text, 4, "display_positions", ArrayJson(dump.DisplayPositions, Vector3Json));
            Property(text, 4, "velocities", ArrayJson(dump.Velocities, Vector3Json));
            Property(text, 4, "real_velocities", ArrayJson(dump.RealVelocities, Vector3Json));
            Property(text, 4, "friction", ArrayJson(dump.Friction, FloatJson));
            Property(text, 4, "static_friction", ArrayJson(dump.StaticFriction, FloatJson));
            Property(text, 4, "collision_normals", ArrayJson(dump.CollisionNormals, Vector3Json), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string SourceJson(params string[] producers)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "repository", Quote("MagicaCloth2"));
            Property(text, 4, "version", Quote(MC2Version));
            Property(text, 4, "commit", Quote(MC2Commit));
            Property(text, 4, "oracle_tier", Quote("A"));
            Property(text, 4, "unity_editor", Quote(Application.unityVersion));
            Property(text, 4, "burst", Quote(PackageVersion(typeof(BurstCompiler).Assembly)));
            Property(text, 4, "collections", Quote(PackageVersion(typeof(NativeList<int>).Assembly)));
            Property(text, 4, "mathematics", Quote(PackageVersion(typeof(float3).Assembly)));
            Property(
                text,
                4,
                "producer",
                StringArray(producers),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string ComparisonJson(OracleCase oracleCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(
                text,
                4,
                "unordered_fields",
                StringArray(
                    "baseline.child_data siblings within one parent",
                    "baseline.baseline_data sibling traversal"
                )
            );
            Property(text, 4, "source_equal_cost_policy", Quote("first_enumerated"));
            Property(text, 4, "hotools_equal_cost_policy", Quote("lowest_vertex_index"));
            Property(text, 4, "compare_to_hotools", oracleCase.CompareToHoTools ? "true" : "false", false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "unordered_fields", StringArray("proxy.edges"));
            Property(
                text,
                4,
                "vertex_to_triangle_record",
                Quote("[flip_flag, triangle_index], DataUtility.Pack12_20 decoded"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(
                text,
                4,
                "raw_order",
                Quote("diagnostic: NativeParallelMultiHashMap sibling order")
            );
            Property(
                text,
                4,
                "canonical_static_membership",
                Quote("per source vertex: (rest-sign-class,target,rest), zero is a separate class"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "record_order", Quote("ordered and numerically significant"), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-5");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "raw_order", Quote("ordered and role-sensitive"));
            Property(
                text,
                4,
                "canonical_membership",
                Quote("diagnostic only; never sorts output quads"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "2e-5");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "fixed_point_scratch", Quote("raw int components before Sum"), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string InputJson(OracleCase oracleCase)
        {
            int count = oracleCase.Positions.Length;
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "task_id", Quote("mc2:mesh_cloth:" + oracleCase.Id));
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(
                text,
                4,
                "vertex_identities",
                StringArray(Enumerable.Range(0, count).Select(index => "mesh:v" + index).ToArray())
            );
            Property(text, 4, "local_positions", ArrayJson(oracleCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "local_normals",
                ArrayJson(Enumerable.Repeat(new float3(0, 0, 1), count), Vector3Json)
            );
            Property(
                text,
                4,
                "local_tangents",
                ArrayJson(Enumerable.Repeat(new float3(1, 0, 0), count), Vector3Json)
            );
            Property(
                text,
                4,
                "uvs",
                ArrayJson(Enumerable.Repeat(new float2(0, 0), count), Vector2Json)
            );
            Property(text, 4, "vertex_attributes", NumberArray(oracleCase.Attributes.Select(value => (int)value)));
            Property(text, 4, "edges", ArrayJson(oracleCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(oracleCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "source_adjacency",
                ArrayJson(oracleCase.Adjacency, values => NumberArray(values)),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyInputJson(ProxyCase proxyCase)
        {
            int count = proxyCase.Positions.Length;
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "task_id", Quote("mc2:mesh_cloth:" + proxyCase.Id));
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(
                text,
                4,
                "vertex_identities",
                StringArray(Enumerable.Range(0, count).Select(index => "mesh:v" + index).ToArray())
            );
            Property(text, 4, "local_positions", ArrayJson(proxyCase.Positions, Vector3Json));
            Property(text, 4, "local_normals", ArrayJson(proxyCase.Normals, Vector3Json));
            Property(text, 4, "local_tangents", ArrayJson(proxyCase.Tangents, Vector3Json));
            Property(text, 4, "uvs", ArrayJson(proxyCase.Uvs, Vector2Json));
            Property(text, 4, "vertex_attributes", NumberArray(proxyCase.Attributes.Select(value => (int)value)));
            Property(text, 4, "lines", ArrayJson(proxyCase.Lines, Int2Json));
            Property(text, 4, "triangles", ArrayJson(proxyCase.Triangles, Int3Json), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceInputJson(DistanceCase distanceCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "local_positions", ArrayJson(distanceCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(distanceCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "parent_indices", NumberArray(distanceCase.Parents));
            Property(text, 4, "edges", ArrayJson(distanceCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(distanceCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "vertex_to_vertex",
                ArrayJson(distanceCase.Adjacency, values => NumberArray(values)),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeInputJson(DistanceRuntimeCase runtimeCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "source_vertex", "0");
            Property(text, 4, "distance_targets", NumberArray(runtimeCase.Targets));
            Property(text, 4, "distance_rest_signed", ArrayJson(runtimeCase.RestSigned, FloatJson));
            Property(text, 4, "next_positions", ArrayJson(P((0, 0, 0), (2, 0, 0), (4, 0, 0)), Vector3Json));
            Property(text, 4, "base_positions", ArrayJson(P((0, 0, 0), (1, 0, 0), (0, 0, 0)), Vector3Json));
            Property(text, 4, "depths", ArrayJson(new[] { 0.5f, 0.0f, 0.0f }, FloatJson));
            Property(text, 4, "friction", ArrayJson(new[] { 0.0f, 0.0f, 0.0f }, FloatJson));
            Property(text, 4, "animation_pose_ratio", "0");
            Property(text, 4, "init_scale", "1");
            Property(text, 4, "scale_ratio", "1");
            Property(text, 4, "simulation_power_y", "1", false);
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingInputJson(BendingCase bendingCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "local_positions", ArrayJson(bendingCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(bendingCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "edges", ArrayJson(bendingCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(bendingCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "init_local_to_world_columns",
                Matrix4x4ColumnsJson(bendingCase.InitLocalToWorld),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeInputJson(BendingRuntimeCase runtimeCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "ordered_quads", ArrayJson(runtimeCase.OrderedQuads, Int4Json));
            Property(
                text,
                4,
                "rest_angle_or_volume",
                ArrayJson(runtimeCase.RestAngleOrVolume, FloatJson)
            );
            Property(
                text,
                4,
                "sign_or_volume",
                NumberArray(runtimeCase.SignOrVolume.Select(value => (int)value))
            );
            Property(text, 4, "next_positions", ArrayJson(runtimeCase.NextPositions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(runtimeCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "depths", ArrayJson(Enumerable.Repeat(0.5f, runtimeCase.NextPositions.Length), FloatJson));
            Property(text, 4, "friction", ArrayJson(new float[runtimeCase.NextPositions.Length], FloatJson));
            Property(text, 4, "stiffness", "1");
            Property(text, 4, "simulation_power_y", "1");
            Property(text, 4, "scale_ratio", FloatJson(runtimeCase.ScaleRatio));
            Property(text, 4, "negative_scale_sign", FloatJson(runtimeCase.NegativeScaleSign), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "proxy", ProxyExpectedJson(dump));
            Property(text, 4, "baseline", BaselineExpectedJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyOnlyExpectedJson(ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "proxy", ProxyFinalJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(
                text,
                6,
                "vertex_attributes",
                NumberArray(dump.FinalAttributes.Select(value => (int)value)),
                false
            );
            text.Append("    }");
            return text.ToString();
        }

        private static string ProxyFinalJson(ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "vertex_attributes", NumberArray(dump.FinalAttributes.Select(value => (int)value)));
            Property(text, 6, "triangles", ArrayJson(dump.Triangles, Int3Json));
            Property(text, 6, "edges", ArrayJson(dump.Edges, Int2Json));
            Property(text, 6, "vertex_to_vertex_ranges", ArrayJson(dump.VertexToVertexRanges, Int2Json));
            Property(text, 6, "vertex_to_vertex_data", NumberArray(dump.VertexToVertexData));
            Property(
                text,
                6,
                "vertex_to_triangle_records",
                ArrayJson(dump.VertexToTriangleRecords, records => ArrayJson(records, Int2Json))
            );
            Property(text, 6, "local_normals", ArrayJson(dump.LocalNormals, Vector3Json));
            Property(text, 6, "local_tangents", ArrayJson(dump.LocalTangents, Vector3Json));
            Property(text, 6, "vertex_bind_pose_positions", ArrayJson(dump.VertexBindPosePositions, Vector3Json));
            Property(
                text,
                6,
                "vertex_bind_pose_rotations",
                ArrayJson(dump.VertexBindPoseRotations, Vector4Json),
                false
            );
            text.Append("    }");
            return text.ToString();
        }

        private static string BaselineExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "parent_indices", NumberArray(dump.Parents));
            Property(text, 6, "child_ranges", ArrayJson(dump.ChildRanges, Int2Json));
            Property(text, 6, "child_data", NumberArray(dump.ChildData));
            Property(text, 6, "baseline_flags", NumberArray(dump.BaselineFlags.Select(value => (int)value)));
            Property(text, 6, "baseline_ranges", ArrayJson(dump.BaselineRanges, Int2Json));
            Property(text, 6, "baseline_data", NumberArray(dump.BaselineData));
            Property(text, 6, "root_indices", NumberArray(dump.Roots));
            Property(text, 6, "depths", ArrayJson(dump.Depths, FloatJson));
            Property(text, 6, "vertex_local_positions", ArrayJson(dump.LocalPositions, Vector3Json));
            Property(text, 6, "vertex_local_rotations", ArrayJson(dump.LocalRotations, Vector4Json), false);
            text.Append("    }");
            return text.ToString();
        }

        private static string DistanceExpectedJson(DistanceDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "raw_packed_indices", UIntArray(dump.PackedIndices));
            Property(text, 4, "distance_ranges", ArrayJson(dump.Ranges, Int2Json));
            Property(text, 4, "distance_targets", NumberArray(dump.Targets));
            Property(
                text,
                4,
                "distance_rest_signed",
                ArrayJson(dump.RestSigned, FloatJson),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeExpectedJson(DistanceRuntimeDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "next_positions", ArrayJson(dump.NextPositions, Vector3Json));
            Property(
                text,
                4,
                "velocity_positions",
                ArrayJson(dump.VelocityPositions, Vector3Json),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingExpectedJson(BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "create_returned_null", dump.CreateReturnedNull ? "true" : "false");
            Property(text, 4, "raw_packed_quads", ULongArray(dump.RawPackedQuads));
            Property(text, 4, "ordered_quads", ArrayJson(dump.OrderedQuads, Int4Json));
            Property(
                text,
                4,
                "rest_angle_or_volume",
                ArrayJson(dump.RestAngleOrVolume, FloatJson)
            );
            Property(text, 4, "sign_or_volume", NumberArray(dump.SignOrVolume));
            Property(text, 4, "diagnostic_write", BendingWriteJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeExpectedJson(BendingRuntimeDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "count_before_sum", NumberArray(dump.CountBeforeSum));
            Property(
                text,
                4,
                "vector_components_before_sum",
                NumberArray(dump.VectorComponentsBeforeSum)
            );
            Property(
                text,
                4,
                "next_positions_after_sum",
                ArrayJson(dump.NextPositionsAfterSum, Vector3Json)
            );
            Property(text, 4, "count_after_sum", NumberArray(dump.CountAfterSum));
            Property(
                text,
                4,
                "vector_after_sum",
                ArrayJson(dump.VectorAfterSum, Vector3Json),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingWriteJson(BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "runtime_consumed", "false");
            Property(text, 6, "write_buffer_count", dump.WriteBufferCount.ToString(CultureInfo.InvariantCulture));
            Property(text, 6, "raw_write_data", UIntArray(dump.RawWriteData));
            Property(text, 6, "raw_write_indices", UIntArray(dump.RawWriteIndices));
            Property(text, 6, "write_ranges", ArrayJson(dump.WriteRanges, Int2Json), false);
            text.Append("    }");
            return text.ToString();
        }

        private static string PackageVersion(Assembly assembly)
        {
            UnityEditor.PackageManager.PackageInfo info =
                UnityEditor.PackageManager.PackageInfo.FindForAssembly(assembly);
            return info != null ? info.version : "unknown";
        }

        private static string CommandLineValue(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int index = 0; index + 1 < arguments.Length; index++)
            {
                if (string.Equals(arguments[index], name, StringComparison.Ordinal))
                {
                    return arguments[index + 1];
                }
            }
            return string.Empty;
        }

        private static void Property(
            StringBuilder text,
            int indent,
            string name,
            string json,
            bool comma = true
        )
        {
            text.Append(' ', indent).Append(Quote(name)).Append(": ").Append(json);
            if (comma)
            {
                text.Append(',');
            }
            text.AppendLine();
        }

        private static string Quote(string value)
        {
            if (value == null)
            {
                return "null";
            }
            var text = new StringBuilder("\"");
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\\': text.Append("\\\\"); break;
                    case '"': text.Append("\\\""); break;
                    case '\n': text.Append("\\n"); break;
                    case '\r': text.Append("\\r"); break;
                    case '\t': text.Append("\\t"); break;
                    default: text.Append(character); break;
                }
            }
            return text.Append('"').ToString();
        }

        private static string StringArray(params string[] values)
        {
            return "[" + string.Join(",", values.Select(Quote)) + "]";
        }

        private static string NumberArray(IEnumerable<int> values)
        {
            return "[" + string.Join(",", values.Select(value => value.ToString(CultureInfo.InvariantCulture))) + "]";
        }

        private static string UIntArray(IEnumerable<uint> values)
        {
            return "[" + string.Join(",", values.Select(value => value.ToString(CultureInfo.InvariantCulture))) + "]";
        }

        private static string ULongArray(IEnumerable<ulong> values)
        {
            return "[" + string.Join(",", values.Select(value => value.ToString(CultureInfo.InvariantCulture))) + "]";
        }

        private static string ArrayJson<T>(IEnumerable<T> values, Func<T, string> convert)
        {
            return "[" + string.Join(",", values.Select(convert)) + "]";
        }

        private static string FloatJson(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
            {
                throw new InvalidDataException("Oracle output contains NaN/Inf");
            }
            return value.ToString("R", CultureInfo.InvariantCulture);
        }

        private static string Vector2Json(float2 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)}]";
        }

        private static string Vector3Json(float3 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)},{FloatJson(value.z)}]";
        }

        private static string Vector4Json(float4 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)},{FloatJson(value.z)},{FloatJson(value.w)}]";
        }

        private static string QuaternionJson(quaternion value)
        {
            return Vector4Json(value.value);
        }

        private static string Matrix4x4ColumnsJson(float4x4 value)
        {
            return ArrayJson(new[] { value.c0, value.c1, value.c2, value.c3 }, Vector4Json);
        }

        private static string Int2Json(int2 value)
        {
            return $"[{value.x},{value.y}]";
        }

        private static string Int3Json(int3 value)
        {
            return $"[{value.x},{value.y},{value.z}]";
        }

        private static string Int4Json(int4 value)
        {
            return $"[{value.x},{value.y},{value.z},{value.w}]";
        }
    }
}
